"""Local setup and account provisioning. / 本地建表和账号令牌管理。"""

import argparse
import hashlib
import json
import secrets
import sys
import uuid
from pathlib import Path
import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "workflow-src"))
from storage.database.db import get_db_url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["init-db", "create-user", "revoke-user", "import-cards"]
    )
    parser.add_argument("--mode", choices=["claude", "claude_coach"], default="claude")
    parser.add_argument("--user-id")
    parser.add_argument("--file", type=Path)
    args = parser.parse_args()
    with psycopg.connect(get_db_url(), connect_timeout=5) as conn:
        if args.action == "init-db":
            conn.execute((ROOT / "schema.sql").read_text(encoding="utf-8"))
            print("Schema ready / 空表已就绪")
        elif args.action == "create-user":
            user_id, token = str(uuid.uuid4()), secrets.token_urlsafe(32)
            conn.execute(
                "INSERT INTO users(id, token_hash, text_chain_variant) VALUES (%s,%s,%s)",
                (user_id, hashlib.sha256(token.encode()).hexdigest(), args.mode),
            )
            # This is the sole intentional credential output; store it privately.
            # 这是唯一有意输出凭证的位置，请私下保存，勿提交仓库。
            print(json.dumps({"user_id": user_id, "token": token}))
        elif args.action == "revoke-user":
            if not args.user_id:
                parser.error("--user-id is required")
            conn.execute(
                "UPDATE users SET token_hash=%s WHERE id=%s",
                (secrets.token_hex(32), args.user_id),
            )
            print("Token revoked / 令牌已撤销")
        else:
            if not args.file:
                parser.error("--file is required")
            cards = json.loads(args.file.read_text(encoding="utf-8"))
            if not isinstance(cards, list) or not cards or len(cards) > 1000:
                parser.error(
                    "Expected 1–1000 owned cards / 请提供 1–1000 张有权使用的方法卡"
                )
            for card in cards:
                for key in ("id", "title", "text", "search_text"):
                    if (
                        not isinstance(card.get(key), str)
                        or not card[key].strip()
                        or len(card[key]) > 6000
                    ):
                        parser.error(f"Invalid {key}")
            from tools.pattern_retriever import get_pattern_retriever

            vectors = []
            for start in range(0, len(cards), 16):
                vectors.extend(
                    get_pattern_retriever()._embed_texts(
                        [c["search_text"] for c in cards[start : start + 16]]
                    )
                )
            if len(vectors) != len(cards) or any(len(v) != 1024 for v in vectors):
                raise ValueError("Invalid embedding dimensions")
            from psycopg.types.json import Jsonb

            for card, vector in zip(cards, vectors):
                conn.execute(
                    "INSERT INTO knowledge_patterns VALUES (%s,%s,%s,%s) ON CONFLICT(chunk_id) "
                    "DO UPDATE SET title=excluded.title,content=excluded.content,embedding=excluded.embedding",
                    (card["id"], card["title"], card["text"], Jsonb(vector)),
                )
            print(f"Imported {len(cards)} cards; restart API / 导入完成，请重启 API")


if __name__ == "__main__":
    main()
