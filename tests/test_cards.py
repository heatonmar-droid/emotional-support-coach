"""Bundled cards and batched import. / 随包方法卡及分批导入检查。"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "workflow-src"))
import manage


class CardsTest(unittest.TestCase):
    def test_role_adapter_uses_supplied_model_and_endpoint(self):
        from tools import llm_client
        from langchain_core.messages import HumanMessage

        client = MagicMock()
        choice = (
            client.__enter__.return_value.chat.completions.create.return_value.choices[
                0
            ]
        )
        choice.message.content = '{"response":"fictional"}'
        choice.finish_reason = "stop"
        with (
            patch.dict(
                "os.environ",
                {
                    "REPLY_API_KEY": "synthetic",
                    "REPLY_BASE_URL": "http://127.0.0.1:9/v1",
                },
            ),
            patch.object(llm_client, "OpenAI", return_value=client) as factory,
        ):
            llm_client.call_llm(
                messages=[HumanMessage(content="fictional")],
                model="developer-selected-model",
                provider="reply",
                temperature=0.2,
                max_completion_tokens=100,
            )
        self.assertEqual(factory.call_args.kwargs["base_url"], "http://127.0.0.1:9/v1")
        sent = client.__enter__.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(sent["model"], "developer-selected-model")
        self.assertEqual(sent["extra_body"], {})

    def test_bundled_cards_import_in_small_batches(self):
        path = ROOT / "knowledge/method-cards.zh-CN.json"
        cards = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(cards), 68)
        self.assertEqual(len({c["id"] for c in cards}), 68)
        for card in cards:
            self.assertEqual(
                set(card), {"id", "title", "category", "text", "search_text"}
            )
            self.assertIn("【边界】", card["text"])
        retriever = MagicMock()
        retriever._embed_texts.side_effect = lambda texts: [[0.0] * 1024 for _ in texts]
        connection = MagicMock()
        with (
            patch.object(
                sys, "argv", ["manage.py", "import-cards", "--file", str(path)]
            ),
            patch.object(manage, "get_db_url", return_value="unused"),
            patch.object(manage.psycopg, "connect", return_value=connection),
            patch(
                "tools.pattern_retriever.get_pattern_retriever", return_value=retriever
            ),
        ):
            manage.main()
        self.assertEqual(
            [len(c.args[0]) for c in retriever._embed_texts.call_args_list],
            [16, 16, 16, 16, 4],
        )
        self.assertEqual(connection.__enter__.return_value.execute.call_count, 68)


if __name__ == "__main__":
    unittest.main()
