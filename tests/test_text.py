"""Offline checks; optional isolated PostgreSQL integration. No paid model calls.
离线检查及可选的隔离数据库集成验证，不调用付费模型。
"""

import hashlib
import json
import os
import secrets
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "workflow-src"))
os.environ["MEM0_TELEMETRY"] = "false"
from langchain_core.messages import AIMessage
import clean_chat_service as core
from clean_chat_service import CleanChatService, SafetyAssessment, _reply_payload
from tools.prompts import load_prompt


def answer(text="这是完全虚构的测试回复。", finish="stop"):
    return AIMessage(
        content=json.dumps(
            {
                "response": text,
                "used_rag_ids": [],
                "used_memory_ids": [],
                "audio": {"intent": "none", "card_key": ""},
            },
            ensure_ascii=False,
        ),
        response_metadata={"finish_reason": finish},
    )


class UnitChecks(unittest.TestCase):
    def test_parser_does_not_log_raw_content(self):
        from tools.json_parsing_robust import parse_json_robust

        marker = "synthetic-private-content-" + uuid.uuid4().hex
        with self.assertLogs("tools.json_parsing_robust", level="WARNING") as logs:
            self.assertEqual(parse_json_robust(marker), {})
        self.assertNotIn(marker, "\n".join(logs.output))

    def test_complete_reply_and_truncation(self):
        service = CleanChatService()
        with patch.object(
            service, "_call", side_effect=[answer(finish="length"), answer()]
        ) as call:
            self.assertEqual(
                service._main_draft("合成输入", [], [], [])[0],
                "这是完全虚构的测试回复。",
            )
            self.assertEqual([c.args[2] for c in call.call_args_list], [1600, 3200])
        with patch.object(service, "_call", return_value=answer(finish="length")):
            with self.assertRaises(ValueError):
                service._main_draft("合成输入", [], [], [])
        with self.assertRaises(ValueError):
            _reply_payload('{"response":"unfinished')
        with self.assertRaises(ValueError):
            _reply_payload('{"response":"response: {bad}"}')

    def test_two_prompts_and_no_audio(self):
        service = CleanChatService()
        for mode, name in [("claude", "daily"), ("claude_coach", "coach")]:
            with patch.object(service, "_call", return_value=answer()) as call:
                response = service._main_draft(
                    "合成输入", [], [], [], text_chain_variant=mode
                )
                self.assertTrue(
                    call.call_args.args[1][0].content.startswith(
                        load_prompt(name, "zh-CN")
                    )
                )
                self.assertEqual(response[3], {"intent": "none", "card_key": ""})
        for name in (
            "daily",
            "coach",
            "safety",
            "memory",
            "memory-use",
            "context-boundary",
        ):
            self.assertTrue(load_prompt(name, "en").strip())
            self.assertTrue(load_prompt(name, "zh-CN").strip())

    def test_provider_failure_has_no_fallback(self):
        service = CleanChatService(
            llm_call=lambda **kw: (_ for _ in ()).throw(RuntimeError("unavailable"))
        )
        with self.assertRaises(RuntimeError):
            service._call(service.claude_main, [], 100)

    def test_safety_evidence_and_failed_safe(self):
        service = CleanChatService()
        payload = {
            "route": "urgent_self_harm",
            "evidence_quote": "not in message",
            "missing": [],
            "environment_action": "none",
            "response_text": "synthetic safety text",
        }
        with patch.object(
            service, "_call", return_value=AIMessage(content=json.dumps(payload))
        ):
            self.assertEqual(
                service._assess_safety("合成输入", [], None).status, "failed_safe"
            )
        payload.update(evidence_quote="合成输入")
        with patch.object(
            service, "_call", return_value=AIMessage(content=json.dumps(payload))
        ):
            self.assertEqual(
                service._assess_safety("合成输入", [], None).route, "urgent_self_harm"
            )

    def test_memory_exact_quote_and_foreign_id(self):
        service = CleanChatService()
        operations = {
            "remember": [
                {"kind": "fact", "scope": "cross_session", "quote": "invented"}
            ],
            "forget_memory_ids": ["some-other-account-id"],
        }
        with patch.object(service, "_write_memory") as write:
            self.assertEqual(
                service._apply_memory_ops_v2(
                    "a", "a", [], operations, "合成输入", "c", "r"
                ),
                ("unchanged", [], []),
            )
            write.assert_not_called()
        self.assertEqual(
            service._episode_quotes(
                {
                    "remember_episode": [
                        {"scope": "cross_session_episode", "quote": "invented"}
                    ]
                },
                "合成输入",
            ),
            [],
        )
        with patch.object(service, "_delete_mem0_memory") as delete:
            self.assertEqual(
                service._delete_requested_episodes(operations, [{"id": "mem0:owned"}]),
                ([], []),
            )
            delete.assert_not_called()

    def test_reset_invalidates_waiting_memory_job(self):
        service = CleanChatService()
        queued = []

        class Deferred:
            def __init__(self, target, **kwargs):
                queued.append(target)

            def start(self):
                pass

        with patch.object(core.threading, "Thread", Deferred):
            self.assertTrue(
                service._write_claude_memory_async(
                    "a", "a", "c", "r", "合成输入", [], []
                )
            )
        service._memory_generation["a"] = 1
        with patch.object(service, "_memory") as read:
            queued[0]()
            read.assert_not_called()

    def test_real_mem0_local_store_with_fake_embeddings(self):
        # Real Mem0/Qdrant storage; only embeddings are replaced, not the memory adapter.
        # 使用真实 Mem0/Qdrant，仅替换外部 embedding 调用。
        from mem0.embeddings.openai import OpenAIEmbedding

        with tempfile.TemporaryDirectory() as directory:
            core._MEM0_OSS_MEMORY = None
            try:
                with (
                    patch.dict(
                        os.environ,
                        {
                            "MEM0_OSS_DATA_DIR": directory,
                            "SILICONFLOW_API_KEY": "offline-test-value",
                            "MEM0_OSS_QDRANT_HOST": "",
                        },
                    ),
                    patch.object(
                        OpenAIEmbedding, "embed", return_value=[1.0] + [0.0] * 1023
                    ),
                ):
                    first = core._mem0_oss_request(
                        "POST",
                        "/v3/memories/add/",
                        {
                            "user_id": "synthetic-a",
                            "messages": [
                                {
                                    "role": "user",
                                    "content": "A completely fictional event.",
                                }
                            ],
                        },
                        None,
                    )
                    self.assertTrue(first.get("results"))
                    own = core._mem0_oss_request(
                        "POST",
                        "/v3/memories/search/",
                        {"query": "event", "filters": {"user_id": "synthetic-a"}},
                        None,
                    )
                    other = core._mem0_oss_request(
                        "POST",
                        "/v3/memories/search/",
                        {"query": "event", "filters": {"user_id": "synthetic-b"}},
                        None,
                    )
                    self.assertTrue(own.get("results"))
                    self.assertFalse(other.get("results"))
                    self.assertTrue(
                        CleanChatService().delete_all_episode_memories(
                            "synthetic-a", "synthetic-a"
                        )
                    )
                    remaining = core._mem0_oss_request(
                        "POST",
                        "/v3/memories/",
                        {"filters": {"user_id": "synthetic-a"}},
                        None,
                    )
                    self.assertFalse(remaining.get("results"))
            finally:
                if core._MEM0_OSS_MEMORY:
                    memory = core._MEM0_OSS_MEMORY
                    memory.vector_store.client.close()
                    history = getattr(memory, "db", None)
                    if history and hasattr(history, "connection"):
                        history.connection.close()
                    # Mem0 also opens a separate migration store on some versions.
                    store = getattr(memory, "_telemetry_vector_store", None)
                    if store and hasattr(store, "client"):
                        store.client.close()
                core._MEM0_OSS_MEMORY = None


@unittest.skipUnless(
    os.environ.get("TEST_DATABASE_URL"),
    "Set TEST_DATABASE_URL to an isolated local PostgreSQL database",
)
class DatabaseChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql

        url = os.environ["TEST_DATABASE_URL"]
        parsed = urlparse(url)
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise RuntimeError("Tests require an isolated loopback database")
        cls.url = url
        cls.schema = "test_" + uuid.uuid4().hex
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls.schema)))
        cls.env = patch.dict(
            os.environ,
            {
                "PGDATABASE_URL": url
                + ("&" if "?" in url else "?")
                + "options=-csearch_path%3D"
                + cls.schema
            },
        )
        cls.env.start()
        import clean_workflow_api as api
        from fastapi.testclient import TestClient

        cls.api = api
        cls.client = TestClient(api.app)
        with api.service._connection() as conn:
            conn.execute((ROOT / "schema.sql").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        import psycopg
        from psycopg import sql

        cls.client.close()
        cls.env.stop()
        with psycopg.connect(cls.url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls.schema))
            )

    def test_authenticated_text_and_persistence(self):
        api, client = self.api, self.client
        tokens = [secrets.token_urlsafe(32) for _ in range(2)]
        users = [str(uuid.uuid4()) for _ in range(2)]
        headers = [{"Authorization": "Bearer " + t} for t in tokens]
        with api.service._connection() as conn:
            for user, token in zip(users, tokens):
                conn.execute(
                    "INSERT INTO users(id,token_hash) VALUES (%s,%s)",
                    (user, hashlib.sha256(token.encode()).hexdigest()),
                )
        self.assertEqual(client.get("/conversations").status_code, 401)
        self.assertEqual(
            client.post(
                "/stream_run",
                headers=headers[0],
                json={"user_input": "hello", "user_id": users[1]},
            ).status_code,
            422,
        )
        for mode in ("daily", "coach"):
            result = client.post(
                "/auth/chat_mode", headers=headers[0], json={"mode": mode}
            )
            self.assertEqual(result.json()["mode"], mode)
        self.assertEqual(
            client.get("/auth/chat_mode", headers=headers[1]).json()["mode"], "daily"
        )

        def llm(**kw):
            system = kw["messages"][0].content
            if system.startswith(load_prompt("safety", "en")):
                return AIMessage(
                    content=json.dumps(
                        {
                            "route": "support",
                            "missing": [],
                            "environment_action": "none",
                            "context_kind": "ordinary_support",
                        }
                    )
                )
            if system.startswith(load_prompt("memory", "en")):
                return AIMessage(
                    content=json.dumps(
                        {
                            "forget_memory_ids": [],
                            "remember_long_term": [],
                            "remember_episode": [],
                        }
                    )
                )
            return answer()

        def events(response):
            return [
                json.loads(s[6:])
                for s in response.text.splitlines()
                if s.startswith("data: ")
            ]

        with (
            patch.object(api.service, "_llm_call", side_effect=llm),
            patch.object(api.service, "_mem0_post", return_value={"results": []}),
            patch.object(api.service, "_write_claude_memory_async", return_value=True),
        ):
            for expected, mode in [("claude", "daily"), ("claude_coach", "coach")]:
                client.post("/auth/chat_mode", headers=headers[0], json={"mode": mode})
                response = client.post(
                    "/stream_run",
                    headers=headers[0],
                    json={"user_input": "完全虚构的测试消息"},
                )
                payload = events(response)
                self.assertEqual(payload[-1]["type"], "workflow_end", payload)
                output = payload[-1]["output"]
                self.assertEqual(output["text_chain_variant"], expected)
                self.assertNotIn("rag_query", output)
                conv = output["conversation_id"]
            self.assertEqual(
                len(
                    client.get("/history/" + conv, headers=headers[0]).json()[
                        "messages"
                    ]
                ),
                4,
            )
            self.assertEqual(
                client.get("/history/" + conv, headers=headers[1]).status_code, 404
            )
            self.assertFalse(
                client.get("/conversations", headers=headers[1]).json()["conversations"]
            )
            other = client.post(
                "/stream_run",
                headers=headers[1],
                json={"user_input": "合成输入", "conversation_id": conv},
            )
            self.assertEqual(events(other)[-1]["type"], "error")
            with patch.object(
                api.service, "_main_draft", side_effect=ValueError("synthetic failure")
            ):
                failed = client.post(
                    "/stream_run", headers=headers[0], json={"user_input": "合成输入"}
                )
                self.assertEqual(events(failed)[-1]["type"], "error")
                self.assertNotIn("synthetic failure", failed.text)
            with api.service._connection() as conn:
                count = conn.execute(
                    "SELECT count(*) FROM chat_messages WHERE user_id=%s AND role='assistant'",
                    (users[0],),
                ).fetchone()[0]
                self.assertEqual(count, 2)
            with patch.object(
                api.service,
                "_assess_safety",
                return_value=SafetyAssessment(
                    route="urgent_self_harm",
                    response_text="合成安全回复",
                    evidence_quote="合成输入",
                ),
            ):
                safe = client.post(
                    "/stream_run", headers=headers[0], json={"user_input": "合成输入"}
                )
                self.assertEqual(events(safe)[-1]["output"]["response"], "合成安全回复")
                self.assertTrue(api.service._safety_state(users[0], users[0]))
            # Exact quote memory persists, and a correction invalidates the old record.
            q = "这是一条虚构的长期事实"
            op = {"remember": [{"kind": "fact", "scope": "cross_session", "quote": q}]}
            status, ids, _ = api.service._apply_memory_ops_v2(
                users[0], users[0], [], op, q, conv, "request-test-memory"
            )
            self.assertEqual(status, "updated")
            current = api.service._memory(users[0], users[0])
            self.assertEqual(current[0]["quote"], q)
            correction = "这是一条纠正后的虚构事实"
            op = {
                "remember": [
                    {
                        "kind": "correction",
                        "scope": "cross_session",
                        "quote": correction,
                        "supersedes_id": ids[0],
                    }
                ]
            }
            status, _, replaced = api.service._apply_memory_ops_v2(
                users[0],
                users[0],
                current,
                op,
                correction,
                conv,
                "request-test-correction",
            )
            self.assertEqual(replaced, ids)
            self.assertEqual(
                api.service._memory(users[0], users[0])[0]["quote"], correction
            )
            self.assertFalse(api.service._memory(users[1], users[1]))
            with patch.object(
                api.service,
                "delete_all_episode_memories",
                side_effect=RuntimeError("synthetic failure"),
            ):
                self.assertEqual(
                    client.post("/reset_all", headers=headers[0]).status_code, 502
                )
                self.assertTrue(
                    client.get("/conversations", headers=headers[0]).json()[
                        "conversations"
                    ]
                )
            with patch.object(
                api.service, "delete_all_episode_memories", return_value=True
            ):
                self.assertEqual(
                    client.post("/reset_all", headers=headers[0]).status_code, 200
                )
            self.assertFalse(
                client.get("/conversations", headers=headers[0]).json()["conversations"]
            )
            self.assertFalse(api.service._memory(users[0], users[0]))
            self.assertIsNone(api.service._safety_state(users[0], users[0]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
