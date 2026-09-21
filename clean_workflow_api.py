"""Authenticated text-only adapter. / 带认证的纯文字 API 适配层。"""

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "workflow-src"))
from clean_chat_service import CleanChatService
from tools.chat_request_guard import normalize_chat_request_id

app = FastAPI(title="Support Assistant Text / 支持助手文字", version="0.1.0")
service = CleanChatService()


def identity(authorization: str = Header(default="", max_length=512)) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Authentication required / 需要认证")
    digest = hashlib.sha256(authorization[7:].encode()).hexdigest()
    try:
        with service._connection() as conn:
            row = conn.execute(
                "SELECT id FROM users WHERE token_hash=%s", (digest,)
            ).fetchone()
    except Exception:
        raise HTTPException(
            503, "Identity service unavailable / 身份校验暂不可用"
        ) from None
    if not row:
        raise HTTPException(401, "Invalid token / 令牌无效")
    return row[0]


class StreamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_input: str = Field(min_length=1, max_length=6000)
    conversation_id: str | None = Field(default=None, max_length=128)
    request_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.:-]{8,80}$")


class ModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["daily", "coach"]


def event(payload):
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def owner(conn, conversation_id, user_id):
    row = conn.execute(
        "SELECT id FROM conversations WHERE id=%s AND user_id=%s",
        (conversation_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Conversation not found / 会话不存在")


@app.get("/health")
def health():
    return {"status": "ok", "chain": "claude-only"}


@app.get("/auth/chat_mode")
def get_mode(user_id: str = Depends(identity)):
    mode = service._text_chain_variant(user_id)
    return {
        "ok": True,
        "mode": "coach" if mode == "claude_coach" else "daily",
        "text_chain_variant": mode,
    }


@app.post("/auth/chat_mode")
def set_mode(request: ModeRequest, user_id: str = Depends(identity)):
    variant = {"daily": "claude", "coach": "claude_coach"}[request.mode]
    with service._connection() as conn:
        conn.execute(
            "UPDATE users SET text_chain_variant=%s WHERE id=%s", (variant, user_id)
        )
    return get_mode(user_id)


@app.post("/session_start")
def greeting(user_id: str = Depends(identity)):
    return {"content": "你好，我是支持助手。今天想从哪里开始？", "user_id": user_id}


@app.get("/conversations")
def conversations(user_id: str = Depends(identity)):
    with service._connection() as conn:
        rows = conn.execute(
            "SELECT id,title,updated_at FROM conversations WHERE user_id=%s ORDER BY updated_at DESC LIMIT 100",
            (user_id,),
        ).fetchall()
    return {
        "conversations": [{"id": r[0], "title": r[1], "updated_at": r[2]} for r in rows]
    }


@app.get("/history/{conversation_id}")
def history(conversation_id: str, user_id: str = Depends(identity)):
    with service._connection() as conn:
        owner(conn, conversation_id, user_id)
    return {"messages": service._history(conversation_id, user_id, user_id)}


@app.post("/stream_run")
async def stream_run(request: StreamRequest, user_id: str = Depends(identity)):
    if not request.user_input.strip():
        raise HTTPException(422, "Empty message / 消息不能为空")
    request_id = normalize_chat_request_id(request.request_id)

    def respond():
        # ponytail: one process-wide lock; use a durable per-user queue before scaling workers.
        # 单进程全局锁；扩展多 worker 前应改为持久化的用户级队列。
        with service._memory_write_lock:
            if request.conversation_id:
                with service._connection() as conn:
                    owner(conn, request.conversation_id, user_id)
            result = service.respond(
                user_input=request.user_input,
                client_id=user_id,
                user_id=user_id,
                conversation_id=request.conversation_id,
                request_id=request_id,
            )
            if not result.get("request_persisted") or not result.get(
                "response_persisted"
            ):
                raise RuntimeError("Reply not committed")
            # Expose only the public reply contract, never diagnostic quotes or retrieved memory.
            # 仅返回公开回复契约，不返回内部诊断原句或检索出的记忆。
            keys = (
                "response",
                "conversation_id",
                "request_id",
                "text_chain_variant",
                "safety_route",
                "emergency_contacts",
                "memory_status",
                "response_persisted",
            )
            return {key: result.get(key) for key in keys}

    async def generate():
        yield event({"type": "workflow_start"})
        yield event(
            {
                "type": "step",
                "message": "正在整理回应…",
                "message_en": "Preparing a reply…",
            }
        )
        try:
            result = await asyncio.to_thread(respond)
        except Exception:
            yield event(
                {
                    "type": "error",
                    "content": "这次回复未完成，请重试。",
                    "content_en": "The reply did not complete. Please retry.",
                }
            )
            return
        yield event({"type": "workflow_end", "output": result})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/reset_all")
def reset_all(user_id: str = Depends(identity)):
    with service._memory_write_lock:
        service._memory_generation[user_id] = (
            service._memory_generation.get(user_id, 0) + 1
        )
        try:
            service.delete_all_episode_memories(user_id, user_id)
        except Exception:
            raise HTTPException(
                502, "Memory deletion incomplete; retry / 记忆删除未完成，请重试"
            ) from None
        with service._connection() as conn:
            conn.execute("DELETE FROM conversations WHERE user_id=%s", (user_id,))
            conn.execute(
                "DELETE FROM patient_clinical_record WHERE user_id=%s", (user_id,)
            )
        with service._safety_fallback_lock:
            service._safety_fallback.pop(user_id, None)
    return {"ok": True, "external_backups_removed": False}
