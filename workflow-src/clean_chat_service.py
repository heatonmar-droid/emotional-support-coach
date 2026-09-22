"""Clean V1 text chain.

This module deliberately does not import graphs, nodes, post processors or
response-shape routing.  It only reuses the shared transport, database and
embedding infrastructure.
"""

from __future__ import annotations
import json
import logging
import os
import re
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from json_repair import repair_json
from storage.database.db import get_db_url
from tools.chat_request_guard import (
    LatestChatRequestRegistry,
    normalize_chat_request_id,
)
from tools.json_parsing_robust import parse_json_robust
from tools.llm_client import call_llm, extract_text
from tools.prompts import load_prompt
from tools.pattern_retriever import get_pattern_retriever

logger = logging.getLogger(__name__)
_ROOT = Path(__file__).resolve().parent.parent
_CONFIG = json.loads(
    (_ROOT / "config" / "chat_clean_v1.json").read_text(encoding="utf-8")
)
_CLAUDE_VARIANTS = {"claude", "claude_coach"}
_MEM0_OSS_MEMORY: Any = None
_MEM0_OSS_LOCK = threading.RLock()


class Mem0BackoffError(RuntimeError):
    """The provider requested a pause; not evidence that a user has no memories."""


def _mem0_vector_config(data_dir: Path) -> dict[str, Any]:
    config: dict[str, Any] = {
        "collection_name": "support_episodes",
        "embedding_model_dims": 1024,
        "on_disk": True,
    }
    host = os.getenv("MEM0_OSS_QDRANT_HOST", "").strip()
    if not host:
        return {**config, "path": str(data_dir / "qdrant")}
    port = int(os.getenv("MEM0_OSS_QDRANT_PORT", "6333"))
    if not 1 <= port <= 65535:
        raise ValueError("MEM0_OSS_QDRANT_PORT must be between 1 and 65535")
    return {**config, "host": host, "port": port, "path": None}


def _mem0_oss_memory():
    global _MEM0_OSS_MEMORY
    with _MEM0_OSS_LOCK:
        if _MEM0_OSS_MEMORY is not None:
            return _MEM0_OSS_MEMORY
        raw_dir = os.getenv("MEM0_OSS_DATA_DIR", "").strip()
        if not raw_dir or not Path(raw_dir).is_absolute():
            raise RuntimeError("MEM0_OSS_DATA_DIR must be an absolute path")
        data_dir = Path(raw_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        api_key = os.getenv("EMBEDDING_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("EMBEDDING_API_KEY is required for Mem0 OSS")
        os.environ["MEM0_TELEMETRY"] = "false"
        os.environ["MEM0_DIR"] = str(data_dir / ".mem0")
        from mem0 import Memory

        _MEM0_OSS_MEMORY = Memory.from_config(
            {
                "version": "v1.1",
                "vector_store": {
                    "provider": "qdrant",
                    "config": _mem0_vector_config(data_dir),
                },
                "llm": {
                    "provider": "deepseek",
                    "config": {
                        "model": "deepseek-chat",
                        "api_key": "disabled",
                        "deepseek_base_url": "http://127.0.0.1:9",
                    },
                },
                "embedder": {
                    "provider": "openai",
                    "config": {
                        "model": os.environ["EMBEDDING_MODEL"],
                        "api_key": api_key,
                        "openai_base_url": os.environ["EMBEDDING_BASE_URL"],
                    },
                },
                "history_db_path": str(data_dir / "history.db"),
            }
        )
        return _MEM0_OSS_MEMORY


def _mem0_oss_request(
    method: str, path: str, payload: dict[str, Any] | None, query: dict[str, str] | None
) -> dict[str, Any]:
    payload = payload or {}
    with _MEM0_OSS_LOCK:
        memory = _mem0_oss_memory()
        if method == "POST" and path == "/v3/memories/search/":
            return memory.search(
                str(payload.get("query") or ""),
                filters=payload.get("filters") or {},
                top_k=max(1, min(int(payload.get("top_k") or 2), 100)),
            )
        if method == "POST" and path == "/v3/memories/add/":
            user_id = str(payload.get("user_id") or "").strip()
            if not user_id:
                raise ValueError("Mem0 OSS user_id is required")
            return memory.add(
                payload.get("messages") or [], user_id=user_id, infer=False
            )
        if method == "POST" and path == "/v3/memories/":
            page_size = max(1, min(int((query or {}).get("page_size") or 100), 100))
            return memory.get_all(filters=payload.get("filters") or {}, top_k=page_size)
        prefix = "/v1/memories/"
        if method == "DELETE" and path.startswith(prefix) and path.endswith("/"):
            memory_id = urllib.parse.unquote(path[len(prefix) : -1]).strip()
            if not memory_id:
                raise ValueError("Mem0 OSS memory_id is required")
            memory.delete(memory_id)
            return {}
        raise ValueError(f"Unsupported Mem0 OSS request: {method} {path}")


def _memory_recorded_at(value: Any) -> str:
    """Provider ingestion timestamp, never inferred event time."""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).isoformat(
            timespec="seconds"
        )
    except (ValueError, TypeError):
        return ""


def _json_object(text: str) -> dict[str, Any] | None:
    """Reuse the shared zero-call parser; return None when no object exists."""
    return parse_json_robust(text, node_name="clean_chat_service") or None


def _reply_text(value: Any) -> str:
    """Validate protocol separation, not conversational wording or user intent."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("这次回应格式异常，请稍后重试。")
    if re.search(
        "(?:^|[\\s{,])['\"]?(?:response|final_response|used_rag_ids|used_memory_ids)['\"]?\\s*:\\s*[\"'{\\[]",
        value,
    ):
        raise ValueError("这次回应格式异常，请稍后重试。")
    return value.strip()


def _reply_payload(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        if not raw.rstrip("` \r\n").endswith("}"):
            raise ValueError("这次回应格式异常，请稍后重试。") from None
        parsed = repair_json(raw, return_objects=True)
    if not isinstance(parsed, dict):
        raise ValueError("这次回应格式异常，请稍后重试。")
    parsed["response"] = _reply_text(parsed.get("response"))
    return parsed


def _content(response: Any) -> str:
    if isinstance(response, AIMessage):
        return extract_text(response)
    content = getattr(response, "content", response)
    return str(content or "").strip()


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str
    temperature: float


@dataclass(frozen=True)
class SafetyAssessment:
    route: str
    response_text: str = ""
    evidence_quote: str = ""
    missing: tuple[str, ...] = ()
    environment_action: str = "none"
    resolved_active_state: bool = False
    memory_write_allowed: bool = True
    status: str = "assessed"


_SAFETY_ROUTES = {
    "support",
    "clarify_safety",
    "urgent_self_harm",
    "urgent_medical",
    "urgent_environment",
}
_SAFETY_MISSING = {"current_intent", "plan", "means_access", "recent_action", "alone"}
_ENVIRONMENT_ACTIONS = {"none", "park_vehicle", "leave_danger", "stop_hazard"}


class CleanChatService:
    """Semantic safety triage, then the minimal Clean V1 response chain."""

    def __init__(
        self,
        *,
        llm_call: Callable[..., Any] = call_llm,
        retriever_factory: Callable[[], Any] = get_pattern_retriever,
    ) -> None:
        self._llm_call = llm_call
        self._retriever_factory = retriever_factory
        self._clean_rag_patterns: list[dict[str, Any]] | None = None
        self._latest_requests = LatestChatRequestRegistry()
        self._safety_fallback: dict[str, tuple[float, dict[str, Any]]] = {}
        self._safety_fallback_lock = threading.Lock()
        self.arm = "claude-only"
        self.claude_main = ModelSpec(**_CONFIG["claude_canary"])
        self.safety = ModelSpec(**_CONFIG["safety_assessor"])
        self.reviewer = ModelSpec(**_CONFIG["memory_extractor"])
        self.main = self.claude_main
        self._memory_write_lock = threading.RLock()
        self._memory_generation = {}

    def respond(
        self,
        *,
        user_input: str,
        client_id: str,
        conversation_id: str | None = None,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        message = (user_input or "").strip()
        if not message:
            raise ValueError("user_input is required")
        if not client_id:
            raise ValueError("client_id is required")
        started = time.perf_counter()
        text_chain_variant = self._text_chain_variant(user_id)
        conversation_id = self._conversation_id(client_id, conversation_id, user_id)
        request_id = normalize_chat_request_id(request_id)
        self._latest_requests.register(conversation_id, request_id)
        history = self._history(conversation_id, client_id, user_id)
        memory = self._memory(client_id, user_id)
        memory = self._with_memory_ids(memory, self._identity(client_id, user_id)[1])
        previous_safety = self._safety_state(client_id, user_id)
        request_persisted = self._save_message(
            client_id, "user", message, conversation_id, user_id, request_id
        )
        if not request_persisted:
            raise RuntimeError("User message not committed")
        rag_query = ""
        rag_items: list[dict[str, Any]] = []
        query_embedding: list[float] | None = None
        episode_items: list[dict[str, Any]] = []
        episode_retrieval: dict[str, Any] = {"status": "disabled"}
        rag_elapsed_ms = 0
        memory_retrieval_elapsed_ms = 0
        generation_elapsed_ms = 0
        draft_result: tuple[str, list[str], list[str], dict[str, str]] | None = None
        rag_query = self._rag_query(message, history)
        rag_started = time.perf_counter()
        rag_items, query_embedding = self._retrieve_act_guides_with_embedding(
            rag_query, current_query=message
        )
        rag_elapsed_ms = int((time.perf_counter() - rag_started) * 1000)
        memory_retrieval_started = time.perf_counter()
        episode_items = self._retrieve_episodes(
            client_id, user_id, query_embedding, rag_query, status=episode_retrieval
        )
        memory_retrieval_elapsed_ms = int(
            (time.perf_counter() - memory_retrieval_started) * 1000
        )

        def timed_safety() -> tuple[SafetyAssessment, int]:
            task_started = time.perf_counter()
            result = self._assess_safety(message, history, previous_safety)
            return (result, int((time.perf_counter() - task_started) * 1000))

        def timed_draft() -> tuple[
            tuple[str, list[str], list[str], dict[str, str]], int
        ]:
            task_started = time.perf_counter()
            result = self._main_draft(
                message,
                history,
                memory,
                rag_items,
                episode_items=episode_items,
                memory_v2=True,
                text_chain_variant=text_chain_variant,
                request_id=request_id,
            )
            return (result, int((time.perf_counter() - task_started) * 1000))

        with ThreadPoolExecutor(max_workers=2) as executor:
            safety_future = executor.submit(timed_safety)
            draft_future = executor.submit(timed_draft)
            safety, safety_elapsed_ms = safety_future.result()
            draft_result, generation_elapsed_ms = draft_future.result()
        if (
            previous_safety
            and (not safety.resolved_active_state)
            and (safety.route in {"support", "clarify_safety"})
        ):
            safety = SafetyAssessment(
                route=str(previous_safety["route"]),
                evidence_quote=safety.evidence_quote
                or str(previous_safety.get("evidence_quote") or ""),
                missing=safety.missing,
                environment_action=str(
                    previous_safety.get("environment_action") or "none"
                ),
                status=f"{safety.status}_latched",
            )
        if safety.resolved_active_state:
            safety_state_persisted = self._write_safety_state(client_id, user_id, None)
        elif safety.route.startswith("urgent_"):
            safety_state_persisted = self._write_safety_state(
                client_id,
                user_id,
                {
                    "route": safety.route,
                    "evidence_quote": safety.evidence_quote,
                    "environment_action": safety.environment_action,
                },
            )
        else:
            safety_state_persisted = True
        if safety.route != "support":
            final_text = _reply_text(self._safety_response(safety))
            response_persisted = self._save_message(
                client_id,
                "assistant",
                final_text,
                conversation_id,
                user_id,
                request_id,
                require_latest_request=True,
            )
            active = safety.route.startswith("urgent_") and (
                not safety.resolved_active_state
            )
            result = {
                "response": final_text,
                "conversation_id": conversation_id,
                "chain": "clean-v1",
                "text_chain_variant": text_chain_variant,
                "arm": self.arm,
                "review_status": "safety_bypass",
                "safety_route": safety.route,
                "safety_assessor_status": safety.status,
                "safety_evidence_quote": safety.evidence_quote,
                "safety_missing": list(safety.missing),
                "safety_mode_active": active,
                "safety_state_persisted": safety_state_persisted,
                "emergency_contacts": self._emergency_contacts(safety),
                "request_id": request_id,
                "request_persisted": request_persisted,
                "response_persisted": response_persisted,
                "request_superseded": not response_persisted,
                "history_messages": len(history),
                "history_chars": sum((len(row["content"]) for row in history)),
                "episode_retrieval": episode_retrieval,
                "rag_query": rag_query,
                "rag_hits": [
                    {"id": item["id"], "title": item["title"], "score": item["score"]}
                    for item in rag_items
                ],
                "rag_used_ids": [],
                "rag_used": False,
                "rag_elapsed_ms": rag_elapsed_ms,
                "generation_elapsed_ms": generation_elapsed_ms,
                "review_elapsed_ms": 0,
                "memory_status": "suppressed_for_safety",
                "memory_v2_enabled": True,
                "memory_write_allowed": safety.memory_write_allowed,
                "profile_retrieved_ids": [
                    str(item["id"]) for item in memory if item.get("id")
                ],
                "episode_retrieved_ids": [str(item["id"]) for item in episode_items],
                "memory_used_ids": [],
                "memory_write_ids": [],
                "memory_superseded_ids": [],
                "memory_retrieval_elapsed_ms": memory_retrieval_elapsed_ms,
                "memory_index_scheduled": False,
                "memory_write_scheduled": False,
                "memory_elapsed_ms": 0,
                "safety_elapsed_ms": safety_elapsed_ms,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            }
            return result
        draft, used_rag_ids, used_memory_ids, audio_decision = draft_result
        review_started = time.perf_counter()
        final_text, review_status = (draft, "disabled_for_claude")
        final_text = _reply_text(final_text)
        review_elapsed_ms = int((time.perf_counter() - review_started) * 1000)
        memory_started = time.perf_counter()
        episode_deleted_ids: list[str] = []
        episode_delete_failed_ids: list[str] = []
        memory_write_scheduled = False
        memory_status = (
            "pending_async"
            if safety.memory_write_allowed
            else "suppressed_for_current_safety_context"
        )
        memory_write_ids, memory_superseded_ids = ([], [])
        memory_elapsed_ms = int((time.perf_counter() - memory_started) * 1000)
        audio_card = None
        response_persisted = self._save_message(
            client_id,
            "assistant",
            final_text,
            conversation_id,
            user_id,
            request_id,
            require_latest_request=True,
            card=audio_card,
        )
        if not response_persisted:
            audio_card = None
        memory_index_scheduled = False
        if safety.memory_write_allowed:
            if request_persisted and response_persisted:
                memory_write_scheduled = self._write_claude_memory_async(
                    client_id,
                    user_id,
                    conversation_id,
                    request_id,
                    message,
                    memory,
                    episode_items,
                )
                memory_status = (
                    "async_scheduled"
                    if memory_write_scheduled
                    else "async_schedule_failed"
                )
            else:
                memory_status = "skipped_unpersisted_turn"
            memory_elapsed_ms = int((time.perf_counter() - memory_started) * 1000)
        result = {
            "response": final_text,
            "conversation_id": conversation_id,
            "chain": "clean-v1",
            "text_chain_variant": text_chain_variant,
            "arm": self.arm,
            "review_status": review_status,
            "safety_route": safety.route,
            "safety_assessor_status": safety.status,
            "safety_evidence_quote": safety.evidence_quote,
            "safety_missing": list(safety.missing),
            "safety_mode_active": False,
            "safety_state_persisted": safety_state_persisted,
            "emergency_contacts": [],
            "request_id": request_id,
            "request_persisted": request_persisted,
            "response_persisted": response_persisted,
            "request_superseded": not response_persisted,
            "history_messages": len(history),
            "history_chars": sum((len(row["content"]) for row in history)),
            "episode_retrieval": episode_retrieval,
            "rag_query": rag_query,
            "rag_hits": [
                {"id": item["id"], "title": item["title"], "score": item["score"]}
                for item in rag_items
            ],
            "rag_used_ids": used_rag_ids,
            "rag_used": bool(used_rag_ids),
            "rag_elapsed_ms": rag_elapsed_ms,
            "generation_elapsed_ms": generation_elapsed_ms,
            "review_elapsed_ms": review_elapsed_ms,
            "audio_intent": audio_decision["intent"],
            "audio_card_key": audio_card["key"] if audio_card else "",
            "action_card": audio_card,
            "memory_status": memory_status,
            "memory_v2_enabled": True,
            "memory_write_allowed": safety.memory_write_allowed,
            "profile_retrieved_ids": [
                str(item["id"]) for item in memory if item.get("id")
            ],
            "episode_retrieved_ids": [str(item["id"]) for item in episode_items],
            "memory_used_ids": used_memory_ids,
            "memory_write_ids": memory_write_ids,
            "memory_superseded_ids": memory_superseded_ids,
            "memory_episode_deleted_ids": episode_deleted_ids,
            "memory_episode_delete_failed_ids": episode_delete_failed_ids,
            "memory_retrieval_elapsed_ms": memory_retrieval_elapsed_ms,
            "memory_index_scheduled": memory_index_scheduled,
            "memory_write_scheduled": memory_write_scheduled,
            "memory_elapsed_ms": memory_elapsed_ms,
            "safety_elapsed_ms": safety_elapsed_ms,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
        return result

    def _text_chain_variant(self, user_id: str | None) -> str:
        if not user_id:
            raise ValueError("Authenticated user required / 需要认证用户")
        with self._connection() as conn:
            row = conn.execute(
                "SELECT text_chain_variant FROM users WHERE id = %s", (user_id,)
            ).fetchone()
        if not row or row[0] not in _CLAUDE_VARIANTS:
            raise ValueError("Invalid text mode / 无效的文字模式")
        return row[0]

    def _call(self, spec: ModelSpec, messages: list[Any], max_tokens: int) -> Any:
        return self._llm_call(
            messages=messages,
            model=spec.model,
            provider=spec.provider,
            temperature=spec.temperature,
            max_completion_tokens=max_tokens,
            timeout_seconds=20,
            response_format={"type": "json_object"},
        )

    def _assess_safety(
        self,
        user_input: str,
        history: list[dict[str, str]],
        active_state: dict[str, Any] | None,
    ) -> SafetyAssessment:
        system = load_prompt("safety", "en")
        recent = [
            row for row in history[-8:] if row.get("role") in {"user", "assistant"}
        ]
        request = json.dumps(
            {
                "active_safety_state": active_state or None,
                "recent_conversation": recent,
                "current_user_message": user_input,
            },
            ensure_ascii=False,
        )
        source_text = "\n".join(
            [
                *(
                    str(row.get("content") or "")
                    for row in recent
                    if row.get("role") == "user"
                ),
                user_input,
            ]
        )
        for attempt in range(2):
            try:
                parsed = _json_object(
                    _content(
                        self._call(
                            self.safety,
                            [
                                SystemMessage(content=system),
                                HumanMessage(content=request),
                            ],
                            520,
                        )
                    )
                )
                if not parsed:
                    logger.warning(
                        "Clean V1 safety assessment returned invalid JSON on attempt %s",
                        attempt + 1,
                    )
                    continue
                route = str(parsed.get("route") or "")
                evidence_quote = str(parsed.get("evidence_quote") or "").strip()
                environment_action = str(parsed.get("environment_action") or "none")
                response_text = str(parsed.get("response_text") or "").strip()
                resolved = parsed.get("resolved_active_state") is True
                memory_write_allowed = (
                    parsed.get("context_kind") != "current_safety_status"
                )
                if (
                    route not in _SAFETY_ROUTES
                    or environment_action not in _ENVIRONMENT_ACTIONS
                ):
                    logger.warning(
                        "Clean V1 safety assessment returned an invalid route/action on attempt %s: %s/%s",
                        attempt + 1,
                        route,
                        environment_action,
                    )
                    continue
                if resolved and (not active_state):
                    resolved = False
                if route != "support" and (
                    not evidence_quote or evidence_quote not in source_text
                ):
                    logger.warning(
                        "Clean V1 safety assessment evidence validation failed on attempt %s: route=%s quote_length=%s",
                        attempt + 1,
                        route,
                        len(evidence_quote),
                    )
                    continue
                if route != "support" and (not response_text):
                    logger.warning(
                        "Clean V1 safety assessment omitted response_text on attempt %s",
                        attempt + 1,
                    )
                    continue
                if resolved and evidence_quote not in user_input:
                    logger.warning(
                        "Clean V1 safety assessment tried to clear state without current-turn evidence"
                    )
                    continue
                raw_missing = (
                    parsed.get("missing")
                    if isinstance(parsed.get("missing"), list)
                    else []
                )
                missing = tuple(
                    dict.fromkeys(
                        (
                            str(item)
                            for item in raw_missing
                            if str(item) in _SAFETY_MISSING
                        )
                    )
                )
                return SafetyAssessment(
                    route=route,
                    response_text=response_text if route != "support" else "",
                    evidence_quote=evidence_quote,
                    missing=missing,
                    environment_action=environment_action,
                    resolved_active_state=resolved,
                    memory_write_allowed=memory_write_allowed,
                    status="assessed" if attempt == 0 else "assessed_after_retry",
                )
            except Exception:
                logger.warning(
                    "Clean V1 safety assessment attempt %s failed", attempt + 1
                )
        return SafetyAssessment(
            route="clarify_safety",
            missing=("current_intent", "plan", "means_access"),
            status="failed_safe",
        )

    @staticmethod
    def _safety_response(assessment: SafetyAssessment) -> str:
        if assessment.response_text:
            return assessment.response_text
        if assessment.resolved_active_state:
            return "谢谢你先完成了这一步。再确认一下：你现在已经和危险源分开，并且身边有人或专业人员正在接手吗？"
        if assessment.status == "failed_safe":
            return "我这次没能可靠完成安全判断，所以先不贸然给方法。请直接告诉我：你现在是否有伤害自己或他人的想法、具体计划，或者危险物就在手边？如果危险正在发生，请立即联系身边的人并拨打120或110。"
        if assessment.route == "clarify_safety":
            return "我想先直接确认一件重要的事：你现在有没有伤害自己或他人的想法、具体计划，或者危险物就在手边？你可以直接回答「没有」「有想法但没计划」或「有计划/工具在身边」。"
        if assessment.route == "urgent_self_harm":
            return "我先不继续分析情绪，现在最重要的是让你和危险物分开。请把它放到够不到的地方，最好交给身边的人；马上联系一个现在能到你身边的人。如果你可能很快伤害自己或他人，请现在拨打120或110；也可以拨打12356获得心理危机支持。你现在能先把危险物放下或离开它，然后告诉我「已经分开」吗？"
        if assessment.route == "urgent_medical":
            return "这种情况不能先当成焦虑处理，也不适合现在做呼吸练习。请立即拨打120，并让身边的人陪着你；不要自行驾车去医院。你现在能先拨120，或请身边的人替你拨打吗？"
        if assessment.environment_action == "park_vehicle":
            return "先不要继续看消息或做练习。请减速，在允许停车的地方安全靠边停车并熄火；停稳前不要回复。等你确认已经安全停好后，我们再继续。"
        if assessment.environment_action == "leave_danger":
            return "现在先停止聊天，尽快到有其他人、能锁门或能求助的安全地点，不要与危险者争辩。如果暴力正在发生，请立即拨打110；有人受伤则同时拨打120。到安全地点后只需告诉我「已到安全处」。"
        return "先停止当前危险动作，和危险源拉开距离，并请身边的人立即介入；必要时拨打110或120。完成这一步前不要继续做任何心理练习。你现在能先离开危险源吗？"

    @staticmethod
    def _emergency_contacts(assessment: SafetyAssessment) -> list[dict[str, str]]:
        if assessment.status == "failed_safe":
            return [
                {"label": "120 急救", "number": "120"},
                {"label": "110 报警", "number": "110"},
            ]
        if assessment.route == "urgent_self_harm":
            return [
                {"label": "120 急救", "number": "120"},
                {"label": "110 报警", "number": "110"},
                {"label": "12356 心理援助", "number": "12356"},
            ]
        if assessment.route == "urgent_medical":
            return [{"label": "120 急救", "number": "120"}]
        if (
            assessment.route == "urgent_environment"
            and assessment.environment_action != "park_vehicle"
        ):
            return [
                {"label": "110 报警", "number": "110"},
                {"label": "120 急救", "number": "120"},
            ]
        return []

    def _main_draft(
        self,
        user_input: str,
        history: list[dict[str, str]],
        memory: list[dict[str, str]],
        rag_items: list[dict[str, Any]],
        *,
        episode_items: list[dict[str, Any]] | None = None,
        memory_v2: bool = False,
        text_chain_variant: str = "claude",
        request_id: str = "",
    ) -> tuple[str, list[str], list[str], dict[str, str]]:
        output_contract = 'Return JSON only: {"response":"final user-facing response","used_rag_ids":["id actually used"],"used_memory_ids":["memory id actually used"],"audio":{"intent":"none|browse|play|change","card_key":"exact key or empty"}}. '
        system = (
            load_prompt("coach", "zh-CN")
            if text_chain_variant == "claude_coach"
            else load_prompt("daily", "zh-CN")
        )
        if rag_items:
            refs = "\n".join((f"- [{item['id']}] {item['text']}" for item in rag_items))
            system += (
                "\n\nOptional reference material. Use only when relevant; do not mention retrieval:\n"
                + refs
            )
        system += load_prompt("memory-use", "en")
        context = self._render_context(
            history, memory, episode_items or [], use_ids=True
        )
        system += context + "\n\nFinal output requirement: " + output_contract
        model = self.claude_main
        messages = [SystemMessage(content=system), HumanMessage(content=user_input)]
        for attempt, budget in enumerate((1600, 3200), 1):
            started = time.monotonic()
            result = self._call(model, messages, budget)
            metadata = getattr(result, "response_metadata", {}) or {}
            finish_reason = metadata.get("finish_reason")
            logger.warning(
                "reply_draft request_id=%s attempt=%s budget=%s finish_reason=%s elapsed_ms=%s",
                request_id,
                attempt,
                budget,
                finish_reason,
                round((time.monotonic() - started) * 1000),
            )
            if finish_reason != "length":
                break
            if attempt == 2:
                raise ValueError("这次回复未完成，请重试。")
        response = _content(result)
        parsed = _reply_payload(response)
        if (
            parsed
            and isinstance(parsed.get("response"), str)
            and parsed["response"].strip()
        ):
            available_ids = {item["id"] for item in rag_items}
            raw_ids = (
                parsed.get("used_rag_ids")
                if isinstance(parsed.get("used_rag_ids"), list)
                else []
            )
            used_ids = [str(item) for item in raw_ids if str(item) in available_ids]
            memory_ids = {
                str(item["id"])
                for item in [*memory, *(episode_items or [])]
                if item.get("id")
            }
            raw_memory_ids = (
                parsed.get("used_memory_ids")
                if isinstance(parsed.get("used_memory_ids"), list)
                else []
            )
            used_memory = [
                str(item) for item in raw_memory_ids if str(item) in memory_ids
            ]
            audio = {"intent": "none", "card_key": ""}
            return (
                parsed["response"].strip(),
                list(dict.fromkeys(used_ids)),
                list(dict.fromkeys(used_memory)),
                audio,
            )
        raise ValueError("这次回应格式异常，请稍后重试。")

    def _recover_memory_ops(
        self,
        user_input: str,
        memory: list[dict[str, Any]],
        model: ModelSpec | None = None,
        episode_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """One semantic fallback for durable memory; it never changes the visible reply."""
        system = load_prompt("memory", "en")
        request = (
            self._render_context([], memory, episode_items, use_ids=True)
            + f"\n\nCurrent user message:\n{user_input}"
        )
        for attempt in range(1):
            try:
                parsed = _json_object(
                    _content(
                        self._call(
                            model or self.main,
                            [
                                SystemMessage(content=system),
                                HumanMessage(content=request),
                            ],
                            280,
                        )
                    )
                )
                if not parsed or not all(
                    (
                        isinstance(parsed.get(key), list)
                        for key in (
                            "forget_memory_ids",
                            "remember_long_term",
                            "remember_episode",
                        )
                    )
                ):
                    continue
                return {
                    "_extraction_status": "extracted",
                    "forget_memory_ids": parsed.get("forget_memory_ids")
                    if isinstance(parsed.get("forget_memory_ids"), list)
                    else [],
                    "remember": parsed.get("remember_long_term")
                    if isinstance(parsed.get("remember_long_term"), list)
                    else [],
                    "remember_episode": parsed.get("remember_episode")
                    if isinstance(parsed.get("remember_episode"), list)
                    else [],
                }
            except Exception:
                logger.warning(
                    "Clean Memory V2 extraction attempt %s failed", attempt + 1
                )
        logger.warning(
            "Clean Memory V2 extraction failed; not an empty successful extraction"
        )
        return {"_extraction_status": "failed"}

    @staticmethod
    def _render_context(
        history: list[dict[str, str]],
        memory: list[dict[str, str]],
        episode_items: list[dict[str, Any]] | None = None,
        *,
        use_ids: bool = False,
    ) -> str:
        parts: list[str] = [load_prompt("context-boundary", "en")]
        if memory:
            parts.append(
                "\n\nExplicit user memory (use only if relevant; current user message wins):\n"
                + "\n".join(
                    (
                        f"- [{(item.get('id') if use_ids else index)}][{item['kind']}] {item['quote']}"
                        for index, item in enumerate(memory)
                    )
                )
            )
        if episode_items:
            parts.append(
                "\n\nRetrieved past dialogue (optional evidence; current user message wins; recorded_at is storage time, not necessarily event time. Preserve explicit event years from user text; do not rewrite them as relative years or infer them from recorded_at):\n"
                + "\n".join(
                    (
                        f"- [{item['id']}]"
                        + (
                            f"[recorded_at={item['recorded_at']}]"
                            if item.get("recorded_at")
                            else ""
                        )
                        + f" {item['text']}"
                        for item in episode_items
                    )
                )
            )
        if history:
            parts.append(
                "\n\nRecent visible conversation:\n"
                + "\n".join((f"{row['role']}: {row['content']}" for row in history))
            )
        return "".join(parts)

    @staticmethod
    def _episode_quotes(memory_ops: dict[str, Any], user_input: str) -> list[str]:
        profile = {
            (str(item.get("kind") or "").strip(), str(item.get("quote") or "").strip())
            for item in memory_ops.get("remember", [])
            if isinstance(item, dict) and str(item.get("quote") or "").strip()
        }
        profile_quotes = {quote for _, quote in profile}
        quotes = [
            quote
            for item in memory_ops.get("remember_episode", [])[:1]
            if isinstance(item, dict)
            and item.get("scope") == "cross_session_episode"
            and (quote := str(item.get("quote") or "").strip())
            and (quote in user_input)
            and (quote not in profile_quotes or ("correction", quote) in profile)
        ]
        if quotes:
            return quotes
        if any(
            (
                isinstance(item, dict) and item.get("scope") == "cross_session_episode"
                for item in memory_ops.get("remember_episode", [])[:1]
            )
        ):
            return [
                quote
                for kind, quote in sorted(profile)
                if kind == "correction" and quote in user_input
            ][:1]
        return []

    @staticmethod
    def _rag_query(user_input: str, history: list[dict[str, str]]) -> str:
        current = str(user_input or "").strip()[-800:]
        if not current:
            return ""
        recent: list[tuple[str, str]] = []
        for row in reversed(history):
            role = str(row.get("role") or "").strip().lower()
            content = str(row.get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                recent.append((role, content[-240:]))
            if len(recent) == 2:
                break
        if not recent:
            return current
        recent.reverse()
        labels = {"user": "用户", "assistant": "支持助手"}
        context = "\n".join((f"{labels[role]}：{content}" for role, content in recent))
        return f"当前用户需求（优先）：\n{current}\n最近一轮上下文（仅用于理解当前需求中的指代，不延续旧话题）：\n{context}"

    def _retrieve_act_guides(
        self, query: str, *, current_query: str | None = None
    ) -> list[dict[str, Any]]:
        items, _ = self._retrieve_act_guides_with_embedding(
            query, current_query=current_query
        )
        return items

    def _retrieve_act_guides_with_embedding(
        self, query: str, *, current_query: str | None = None
    ) -> tuple[list[dict[str, Any]], list[float] | None]:
        try:
            retriever = self._retriever_factory()
            if self._clean_rag_patterns is None:
                self._clean_rag_patterns = retriever._load_patterns("clean_guide")
            if not self._clean_rag_patterns:
                return [], None
            current = str(current_query or query).strip()
            if current and current != query:
                if hasattr(retriever, "_embed_texts"):
                    embedding, context_embedding = retriever._embed_texts(
                        [current, query]
                    )
                else:
                    embedding = retriever._embed_text(current)
                    context_embedding = retriever._embed_text(query)
            else:
                embedding = retriever._embed_text(query)
                context_embedding = embedding
            if self._clean_rag_patterns is None:
                self._clean_rag_patterns = retriever._load_patterns("clean_guide")

            def rank(vector: list[float]) -> list[tuple[float, dict[str, Any]]]:
                scored = [
                    (
                        retriever._cosine_similarity(vector, pattern["embedding"]),
                        pattern,
                    )
                    for pattern in self._clean_rag_patterns or []
                    if pattern.get("embedding") is not None
                ]
                scored.sort(key=lambda item: item[0], reverse=True)
                return scored

            current_ranked = rank(embedding)
            selected = current_ranked[: int(_CONFIG["rag_top_k"])]
            if context_embedding is not embedding and selected:
                context_ranked = rank(context_embedding)
                contextual = next(
                    (
                        item
                        for item in context_ranked
                        if item[1].get("chunk_id") != selected[0][1].get("chunk_id")
                    ),
                    None,
                )
                if contextual is not None and len(selected) > 1:
                    selected[1] = contextual
            return (
                [
                    {
                        "id": str(p.get("chunk_id") or ""),
                        "title": str(p.get("scene_type") or "完整方法卡"),
                        "score": round(float(score), 4),
                        "text": str(p.get("reference_text") or p.get("content") or ""),
                    }
                    for score, p in selected
                    if str(p.get("reference_text") or p.get("content") or "").strip()
                ],
                embedding,
            )
        except Exception:
            logger.error("Clean V1 RAG retrieval failed")
            return ([], None)

    def _retrieve_episodes(
        self,
        client_id: str,
        user_id: str | None,
        query_embedding: list[float] | None,
        query_text: str,
        *,
        status: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        top_k = max(1, min(int(_CONFIG.get("episode_top_k", 2)), 8))
        status = status if status is not None else {}
        status["status"] = "ok"
        identity = self._identity(client_id, user_id)[1]
        try:
            payload = self._mem0_post(
                "search",
                {"query": query_text, "filters": {"user_id": identity}, "top_k": top_k},
            )
            return [
                {
                    "id": f"mem0:{item['id']}",
                    "text": str(item.get("memory") or "").strip(),
                    "score": round(float(item.get("score") or 0.0), 4),
                    "recorded_at": _memory_recorded_at(item.get("created_at")),
                }
                for item in payload.get("results", [])
                if item.get("id") and str(item.get("memory") or "").strip()
            ]
        except Mem0BackoffError:
            status["status"] = "backoff"
            return []
        except urllib.error.HTTPError as exc:
            status.update(
                status="rate_limited" if exc.code == 429 else "unavailable",
                http_status=exc.code,
            )
            logger.warning("Clean Mem0 retrieval unavailable http_status=%s", exc.code)
            return []
        except Exception:
            status["status"] = "unavailable"
            logger.error("Clean Mem0 episode retrieval failed")
            return []

    def _write_claude_memory_async(
        self,
        client_id: str,
        user_id: str | None,
        conversation_id: str,
        request_id: str,
        user_input: str,
        previous_memory: list[dict[str, Any]],
        episode_items: list[dict[str, Any]],
    ) -> bool:

        identity = self._identity(client_id, user_id)[1]
        generation = self._memory_generation.get(identity, 0)

        def worker() -> None:
            try:
                with self._memory_write_lock:
                    if generation != self._memory_generation.get(identity, 0):
                        return
                    current = (
                        self._with_memory_ids(
                            self._memory(client_id, user_id), identity
                        )
                        or previous_memory
                    )
                    memory_ops = self._recover_memory_ops(
                        user_input, current, self.reviewer, episode_items
                    )
                    deleted_ids, delete_failed_ids = self._delete_requested_episodes(
                        memory_ops, episode_items
                    )
                    status, write_ids, superseded_ids = self._apply_memory_ops_v2(
                        client_id,
                        user_id,
                        current,
                        memory_ops,
                        user_input,
                        conversation_id,
                        request_id,
                    )
                    episode_quotes = self._episode_quotes(memory_ops, user_input)
                    mem0_provider = True
                    should_index = (
                        bool(episode_quotes) if mem0_provider else bool(write_ids)
                    )
                    if should_index and status != "failed":
                        self._index_episode_async(
                            client_id,
                            user_id,
                            conversation_id,
                            episode_quotes[0] if mem0_provider else user_input,
                        )
                    log = (
                        logger.warning
                        if status == "failed" or delete_failed_ids
                        else logger.info
                    )
                    log(
                        "Claude memory write finished status=%s writes=%s superseded=%s deleted=%s delete_failed=%s",
                        status,
                        len(write_ids),
                        len(superseded_ids),
                        len(deleted_ids),
                        len(delete_failed_ids),
                    )
            except Exception:
                logger.error("Claude asynchronous memory write failed")

        try:
            threading.Thread(target=worker, daemon=True).start()
            return True
        except Exception:
            logger.error("Claude asynchronous memory write could not be scheduled")
            return False

    def _index_episode_async(self, client_id, user_id, conversation_id, user_input):
        self._index_mem0_episode(self._identity(client_id, user_id)[1], user_input)
        return True

    @staticmethod
    def _mem0_request(
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return _mem0_oss_request(method, path, payload, query)

    @classmethod
    def _mem0_post(cls, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return cls._mem0_request("POST", f"/v3/memories/{path}/", payload)

    @classmethod
    def _delete_mem0_memory(cls, memory_id: str) -> None:
        remote_id = str(memory_id).removeprefix("mem0:").strip()
        if not remote_id:
            raise ValueError("memory_id is required")
        cls._mem0_request(
            "DELETE", f"/v1/memories/{urllib.parse.quote(remote_id, safe='')}/"
        )

    def delete_all_episode_memories(
        self, client_id: str, user_id: str | None = None
    ) -> bool:
        identity = self._identity(client_id, user_id)[1]
        for _ in range(20):
            page = self._mem0_request(
                "POST",
                "/v3/memories/",
                {"filters": {"user_id": identity}},
                {"page": "1", "page_size": "100"},
            )
            memory_ids = [
                str(item.get("id") or "").strip()
                for item in page.get("results", [])
                if isinstance(item, dict) and str(item.get("id") or "").strip()
            ]
            if not memory_ids:
                return True
            for memory_id in memory_ids:
                self._delete_mem0_memory(memory_id)
        raise RuntimeError("Mem0 user memory exceeds the deletion safety ceiling")

    def _delete_requested_episodes(
        self, memory_ops: dict[str, Any], episode_items: list[dict[str, Any]]
    ) -> tuple[list[str], list[str]]:
        available = {
            str(item.get("id") or "")
            for item in episode_items
            if str(item.get("id") or "").startswith("mem0:")
        }
        requested = memory_ops.get("forget_memory_ids")
        corrections = [
            item
            for item in memory_ops.get("remember", [])
            if isinstance(item, dict) and item.get("kind") == "correction"
        ]
        correction_targets = [
            str(item.get("supersedes_id") or "")
            for item in corrections
            if str(item.get("supersedes_id") or "").strip()
        ]
        if corrections and (not correction_targets) and (len(available) == 1):
            correction_targets = list(available)
        targets = list(
            dict.fromkeys(
                (
                    resolved
                    for item in (
                        [*requested, *correction_targets]
                        if isinstance(requested, list)
                        else correction_targets
                    )
                    if (
                        resolved := (
                            str(item) if str(item) in available else "mem0:" + str(item)
                        )
                    )
                    in available
                )
            )
        )
        deleted: list[str] = []
        failed: list[str] = []
        for memory_id in targets:
            try:
                self._delete_mem0_memory(memory_id)
                deleted.append(memory_id)
            except Exception:
                logger.error("Episode deletion failed")
                failed.append(memory_id)
        return (deleted, failed)

    def _index_mem0_episode(self, identity: str, user_input: str) -> None:
        try:
            self._mem0_post(
                "add",
                {
                    "messages": [{"role": "user", "content": user_input}],
                    "user_id": identity,
                    "infer": False,
                },
            )
        except Exception:
            logger.error("Clean Mem0 episode indexing failed")

    @staticmethod
    def _memory_id(
        identity: str, kind: str, quote: str, source_request_id: str = ""
    ) -> str:
        seed = "|".join((identity, kind, quote, source_request_id))
        return "memory_" + uuid.uuid5(uuid.NAMESPACE_URL, seed).hex[:20]

    def _with_memory_ids(
        self, items: list[dict[str, Any]], identity: str
    ) -> list[dict[str, Any]]:
        enriched = []
        for item in items:
            if not isinstance(item, dict):
                continue
            value = dict(item)
            value["id"] = str(
                value.get("id")
                or self._memory_id(
                    identity,
                    str(value.get("kind") or "context"),
                    str(value.get("quote") or ""),
                    str(value.get("source_request_id") or ""),
                )
            )
            enriched.append(value)
        return enriched

    def _apply_memory_ops_v2(
        self,
        client_id: str,
        user_id: str | None,
        current: list[dict[str, Any]],
        memory_ops: dict[str, Any],
        user_input: str,
        conversation_id: str,
        request_id: str,
    ) -> tuple[str, list[str], list[str]]:
        if memory_ops.get("_extraction_status") == "failed":
            return ("failed", [], [])
        identity = self._identity(client_id, user_id)[1]
        records = [
            {key: value for key, value in item.items() if key not in {"source"}}
            for item in self._with_memory_ids(current, identity)
            if item.get("source") != "legacy"
            and item.get("kind") in {"fact", "boundary", "correction"}
        ]
        for record in records:
            record.setdefault("status", "active")
        active_by_id = {
            str(item["id"]): item
            for item in records
            if item.get("status") == "active" and item.get("id")
        }
        changed_ids: list[str] = []
        now = datetime.now(timezone.utc).isoformat()
        raw_forget = memory_ops.get("forget_memory_ids")
        if isinstance(raw_forget, list):
            for raw_id in raw_forget:
                memory_id = str(raw_id)
                target = active_by_id.get(memory_id)
                if target is None:
                    continue
                target["status"] = "forgotten"
                target["invalidated_at"] = now
                changed_ids.append(memory_id)
                active_by_id.pop(memory_id, None)
        write_ids: list[str] = []
        raw_remember = memory_ops.get("remember")
        if isinstance(raw_remember, list):
            known = {
                (str(item.get("kind") or ""), str(item.get("quote") or ""))
                for item in records
                if item.get("status") == "active"
            }
            for item in raw_remember:
                if not isinstance(item, dict):
                    continue
                kind = str(item.get("kind") or "").strip()
                scope = str(item.get("scope") or "").strip()
                quote = str(item.get("quote") or "").strip()[:240]
                if (
                    scope != "cross_session"
                    or kind not in {"fact", "boundary", "correction"}
                    or (not quote)
                    or (quote not in user_input)
                ):
                    continue
                candidate = (kind, quote)
                if candidate in known:
                    continue
                supersedes_id = str(item.get("supersedes_id") or "").strip()
                superseded = active_by_id.get(supersedes_id)
                if superseded is None and kind == "correction":
                    candidates = [
                        record
                        for record in active_by_id.values()
                        if record.get("kind") in {"fact", "correction"}
                    ]
                    if len(candidates) == 1:
                        superseded = candidates[0]
                        supersedes_id = str(superseded["id"])
                memory_id = self._memory_id(identity, kind, quote, request_id)
                if superseded is not None:
                    superseded["status"] = "superseded"
                    superseded["invalidated_at"] = now
                    superseded["superseded_by"] = memory_id
                    changed_ids.append(supersedes_id)
                    active_by_id.pop(supersedes_id, None)
                record = {
                    "id": memory_id,
                    "kind": kind,
                    "quote": quote,
                    "source_request_id": request_id,
                    "source_conversation_id": conversation_id,
                    "created_at": now,
                    "status": "active",
                }
                if superseded is not None:
                    record["supersedes_id"] = supersedes_id
                records.append(record)
                active_by_id[memory_id] = record
                known.add(candidate)
                write_ids.append(memory_id)
        active = [item for item in records if item.get("status") == "active"]
        limit = int(_CONFIG["memory_limit"])
        for overflow in active[:-limit] if len(active) > limit else []:
            overflow["status"] = "superseded"
            overflow["invalidated_at"] = now
            changed_ids.append(str(overflow["id"]))
        changed_ids = list(dict.fromkeys(changed_ids))
        if not write_ids and (not changed_ids):
            return ("unchanged", [], [])
        if not self._write_memory(client_id, user_id, records):
            return ("failed", [], [])
        return ("updated", write_ids, changed_ids)

    def _connection(self):
        import psycopg

        url = get_db_url()
        if not url:
            raise RuntimeError("PGDATABASE_URL is not available")
        return psycopg.connect(url, autocommit=False, connect_timeout=5)

    @staticmethod
    def _identity(client_id: str, user_id: str | None) -> tuple[str, str]:
        return ("user_id", user_id) if user_id else ("client_id", client_id)

    def _conversation_id(
        self, client_id: str, conversation_id: str | None, user_id: str | None
    ) -> str:
        try:
            with self._connection() as conn:
                query_col, query_val = self._identity(client_id, user_id)
                if conversation_id:
                    owned = conn.execute(
                        f"SELECT id FROM conversations WHERE id = %s AND {query_col} = %s",
                        (conversation_id, query_val),
                    ).fetchone()
                    if owned:
                        return str(owned[0])
                else:
                    latest = conn.execute(
                        f"SELECT id FROM conversations WHERE {query_col} = %s ORDER BY updated_at DESC LIMIT 1",
                        (query_val,),
                    ).fetchone()
                    if latest:
                        return str(latest[0])
                conversation_id = f"clean_{uuid.uuid4().hex}"
                conn.execute(
                    "INSERT INTO conversations (id, client_id, title, user_id) VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                    (conversation_id, client_id, "Clean V1 测试对话", user_id or ""),
                )
        except Exception:
            raise RuntimeError("Conversation storage unavailable") from None
        return conversation_id or f"clean_{uuid.uuid4().hex}"

    def _history(
        self, conversation_id: str, client_id: str, user_id: str | None = None
    ) -> list[dict[str, str]]:
        try:
            limit = int(_CONFIG["history_messages"])
            query_col, query_val = self._identity(client_id, user_id)
            with self._connection() as conn:
                rows = conn.execute(
                    f"SELECT role, content, card FROM chat_messages WHERE conversation_id = %s AND {query_col} = %s ORDER BY id DESC LIMIT %s",
                    (conversation_id, query_val, limit),
                ).fetchall()
            history = []
            for row in reversed(rows):
                item = {"role": str(row[0]), "content": str(row[1])}
                card = row[2] if len(row) > 2 else None
                if isinstance(card, dict) and card.get("type") == "audio":
                    item["audio_card_key"] = str(card.get("key") or "")
                history.append(item)
            turns: list[list[dict[str, str]]] = []
            for item in history:
                if item["role"] == "user":
                    turns.append([])
                if turns:
                    turns[-1].append(item)
            selected: list[list[dict[str, str]]] = []
            size = 0
            for turn in reversed(turns):
                length = sum((len(item["content"]) for item in turn))
                if selected and size + length > int(
                    _CONFIG.get("history_char_budget", 10000)
                ):
                    break
                selected.append(turn)
                size += length
            return [item for turn in reversed(selected) for item in turn]
        except Exception:
            raise RuntimeError("History storage unavailable") from None

    def _save_message(
        self,
        client_id: str,
        role: str,
        content: str,
        conversation_id: str,
        user_id: str | None,
        request_id: str,
        *,
        require_latest_request: bool = False,
        card: dict[str, Any] | None = None,
    ) -> bool:
        try:
            from psycopg.types.json import Jsonb

            card_value = Jsonb(card) if isinstance(card, dict) else None
            with self._connection() as conn:
                if require_latest_request and (
                    not self._latest_requests.is_latest(conversation_id, request_id)
                ):
                    return False
                if require_latest_request:
                    inserted = conn.execute(
                        "\n                        INSERT INTO chat_messages (client_id, role, content, conversation_id, user_id, request_id, card)\n                        SELECT %s, %s, %s, %s, %s, %s, %s\n                        WHERE %s = (\n                            SELECT request_id FROM chat_messages\n                            WHERE conversation_id = %s AND role = 'user' AND request_id IS NOT NULL\n                            ORDER BY id DESC LIMIT 1\n                        )\n                        RETURNING id\n                        ",
                        (
                            client_id,
                            role,
                            content,
                            conversation_id,
                            user_id or "",
                            request_id,
                            card_value,
                            request_id,
                            conversation_id,
                        ),
                    ).fetchone()
                    if inserted is None:
                        return False
                else:
                    conn.execute(
                        "INSERT INTO chat_messages (client_id, role, content, conversation_id, user_id, request_id, card) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (
                            client_id,
                            role,
                            content,
                            conversation_id,
                            user_id or "",
                            request_id,
                            card_value,
                        ),
                    )
                conn.execute(
                    "UPDATE conversations SET updated_at = NOW() WHERE id = %s",
                    (conversation_id,),
                )
            return True
        except Exception:
            logger.error("Clean V1 message persistence failed")
            return False

    def _memory(
        self, client_id: str, user_id: str | None = None
    ) -> list[dict[str, str]]:
        try:
            query_col, query_val = self._identity(client_id, user_id)
            with self._connection() as conn:
                row = conn.execute(
                    f"SELECT relationship_memory, basic_info, recent_session_summaries FROM patient_clinical_record WHERE {query_col} = %s",
                    (query_val,),
                ).fetchone()
            payload = row[0] or {} if row else {}
            items = (
                payload.get("support_memory_v1", {}).get("items", [])
                if isinstance(payload, dict)
                else []
            )
            normalized: list[dict[str, str]] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                kind = str(item.get("kind") or "").strip()
                quote = str(
                    item.get("quote")
                    or item.get("source_quote")
                    or item.get("text")
                    or ""
                ).strip()
                status = str(item.get("status") or "active").strip()
                if (
                    kind in {"fact", "boundary", "correction"}
                    and quote
                    and (status == "active")
                ):
                    normalized_item = {
                        "kind": kind,
                        "quote": quote[:240],
                        "source": "clean",
                        "status": "active",
                    }
                    for key in (
                        "id",
                        "source_request_id",
                        "source_conversation_id",
                        "created_at",
                        "supersedes_id",
                    ):
                        if item.get(key) not in {None, ""}:
                            normalized_item[key] = str(item[key])
                    normalized.append(normalized_item)
            legacy: list[dict[str, str]] = []
            if isinstance(payload, dict):
                for field, kind in (
                    ("boundary_preferences", "boundary"),
                    ("preferred_tone", "boundary"),
                    ("life_anchors", "context"),
                ):
                    values = payload.get(field)
                    if isinstance(values, list):
                        for value in reversed(values):
                            text = str(value or "").strip()
                            if text:
                                legacy.append(
                                    {
                                        "kind": kind,
                                        "quote": text[:240],
                                        "source": "legacy",
                                    }
                                )
                episodes = payload.get("episodes")
                if isinstance(episodes, list):
                    for episode in reversed(episodes):
                        if (
                            not isinstance(episode, dict)
                            or episode.get("status") == "forgotten"
                        ):
                            continue
                        text = str(episode.get("text") or "").strip()
                        if text:
                            legacy.append(
                                {
                                    "kind": "context",
                                    "quote": text[:240],
                                    "source": "legacy",
                                }
                            )
            if row and str(row[1] or "").strip():
                legacy.append(
                    {
                        "kind": "context",
                        "quote": str(row[1]).strip()[:240],
                        "source": "legacy",
                    }
                )
            summaries = row[2] if row else None
            if isinstance(summaries, list):
                for summary in reversed(summaries[-4:]):
                    text = self._summary_user_side(summary)
                    if text:
                        legacy.append(
                            {"kind": "context", "quote": text[:240], "source": "legacy"}
                        )
            seen: set[str] = set()
            merged: list[dict[str, str]] = []
            for item in [*normalized, *legacy]:
                if item["quote"] in seen:
                    continue
                seen.add(item["quote"])
                merged.append(item)
            return merged[: int(_CONFIG["memory_limit"])]
        except Exception:
            logger.error("Clean V1 memory fetch failed")
            return []

    @staticmethod
    def _summary_user_side(value: Any) -> str:
        text = str(value or "").strip()
        for prefix in ("来访:", "来访："):
            if text.startswith(prefix):
                text = text[len(prefix) :]
                break
        for marker in ("| 支持助手:", "| 支持助手：", "支持助手:", "支持助手："):
            index = text.find(marker)
            if index > 0:
                text = text[:index]
                break
        return text.strip().rstrip("|").strip()

    def _fallback_safety_state(self, identity: str) -> dict[str, Any] | None:
        with self._safety_fallback_lock:
            entry = self._safety_fallback.get(identity)
            if not entry:
                return None
            expires_at, state = entry
            if expires_at <= time.time():
                self._safety_fallback.pop(identity, None)
                return None
            return dict(state)

    def _safety_state(
        self, client_id: str, user_id: str | None = None
    ) -> dict[str, Any] | None:
        _, identity = self._identity(client_id, user_id)
        try:
            query_col, query_val = self._identity(client_id, user_id)
            with self._connection() as conn:
                row = conn.execute(
                    f"SELECT relationship_memory FROM patient_clinical_record WHERE {query_col} = %s",
                    (query_val,),
                ).fetchone()
            payload = row[0] or {} if row else {}
            state = (
                payload.get("clean_safety_v1") if isinstance(payload, dict) else None
            )
            if not isinstance(state, dict) or state.get("active") is not True:
                return self._fallback_safety_state(identity)
            route = str(state.get("route") or "")
            if route not in {
                "urgent_self_harm",
                "urgent_medical",
                "urgent_environment",
            }:
                return None
            updated_at = datetime.fromisoformat(
                str(state.get("updated_at") or "").replace("Z", "+00:00")
            )
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            ttl = timedelta(seconds=int(_CONFIG.get("safety_state_ttl_seconds", 14400)))
            if datetime.now(timezone.utc) - updated_at > ttl:
                self._write_safety_state(client_id, user_id, None)
                return None
            return {
                "route": route,
                "evidence_quote": str(state.get("evidence_quote") or ""),
                "environment_action": str(state.get("environment_action") or "none"),
            }
        except Exception:
            logger.error("Clean V1 safety state fetch failed")
            return self._fallback_safety_state(identity)

    def _write_safety_state(
        self, client_id: str, user_id: str | None, state: dict[str, str] | None
    ) -> bool:
        query_col, query_val = self._identity(client_id, user_id)
        try:
            from psycopg.types.json import Jsonb

            with self._connection() as conn:
                current = conn.execute(
                    f"SELECT relationship_memory FROM patient_clinical_record WHERE {query_col} = %s FOR UPDATE",
                    (query_val,),
                ).fetchone()
                payload = current[0] or {} if current else {}
                if state is None:
                    payload.pop("clean_safety_v1", None)
                else:
                    payload["clean_safety_v1"] = {
                        "version": 1,
                        "active": True,
                        "route": state["route"],
                        "evidence_quote": state.get("evidence_quote", "")[:240],
                        "environment_action": state.get("environment_action", "none"),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                updated = conn.execute(
                    f"UPDATE patient_clinical_record SET relationship_memory = %s, updated_at = NOW() WHERE {query_col} = %s",
                    (Jsonb(payload), query_val),
                )
                if updated.rowcount == 0 and state is not None:
                    conn.execute(
                        "INSERT INTO patient_clinical_record (client_id, user_id, relationship_memory) VALUES (%s, %s, %s)",
                        (client_id, user_id or "", Jsonb(payload)),
                    )
            with self._safety_fallback_lock:
                self._safety_fallback.pop(query_val, None)
            return True
        except Exception:
            logger.error("Clean V1 safety state persistence failed")
            with self._safety_fallback_lock:
                if state is None:
                    self._safety_fallback.pop(query_val, None)
                else:
                    self._safety_fallback[query_val] = (
                        time.time()
                        + int(_CONFIG.get("safety_state_ttl_seconds", 14400)),
                        dict(state),
                    )
            return False

    def _write_memory(
        self, client_id: str, user_id: str | None, items: list[dict[str, str]]
    ) -> bool:
        try:
            from psycopg.types.json import Jsonb

            query_col, query_val = self._identity(client_id, user_id)
            with self._connection() as conn:
                current = conn.execute(
                    f"SELECT relationship_memory FROM patient_clinical_record WHERE {query_col} = %s",
                    (query_val,),
                ).fetchone()
                payload = current[0] or {} if current else {}
                payload = self._memory_v2_storage_payload(payload, items)
                updated = conn.execute(
                    f"UPDATE patient_clinical_record SET relationship_memory = %s, updated_at = NOW() WHERE {query_col} = %s",
                    (Jsonb(payload), query_val),
                )
                if updated.rowcount == 0:
                    conn.execute(
                        "INSERT INTO patient_clinical_record (client_id, user_id, relationship_memory) VALUES (%s, %s, %s)",
                        (client_id, user_id or "", Jsonb(payload)),
                    )
            return True
        except Exception:
            logger.error("Clean V1 memory persistence failed")
            return False

    @staticmethod
    def _memory_v2_storage_payload(
        payload: dict[str, Any] | Any, items: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Keep the rollback-visible namespace active-only and archive tombstones separately."""
        value = dict(payload) if isinstance(payload, dict) else {}
        previous_visible = value.get("support_memory_v1", {}).get("items", [])
        previous_history = value.get("support_memory_v2_history", {}).get("items", [])
        history_by_id = {
            str(item["id"]): dict(item)
            for item in [*previous_history, *previous_visible]
            if isinstance(item, dict)
            and item.get("id")
            and (str(item.get("status") or "active") != "active")
        }
        active_by_id = {
            str(item["id"]): dict(item)
            for item in previous_visible
            if isinstance(item, dict)
            and item.get("id")
            and (str(item.get("status") or "active") == "active")
        }
        for item in items:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            memory_id = str(item["id"])
            record = dict(item)
            if str(record.get("status") or "active") == "active":
                active_by_id[memory_id] = record
                history_by_id.pop(memory_id, None)
            else:
                active_by_id.pop(memory_id, None)
                history_by_id[memory_id] = record
        value["support_memory_v1"] = {
            "version": 3,
            "items": list(active_by_id.values()),
        }
        value["support_memory_v2_history"] = {
            "version": 1,
            "items": list(history_by_id.values()),
        }
        return value
