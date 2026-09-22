"""Recipient-owned clean_guide corpus, retaining the production ranking interface.
仅检索使用者自己的方法卡，保留生产排序接口；不导入咨询原文。
"""

import math
import os
from functools import lru_cache
import psycopg
from openai import OpenAI
from storage.database.db import get_db_url


class PatternRetriever:
    def _embed_texts(self, texts):
        key = os.environ.get("EMBEDDING_API_KEY", "").strip()
        if not key:
            raise RuntimeError("Set EMBEDDING_API_KEY")
        with OpenAI(
            api_key=key,
            base_url=os.environ["EMBEDDING_BASE_URL"],
            timeout=12,
            max_retries=0,
        ) as client:
            response = client.embeddings.create(model=os.environ["EMBEDDING_MODEL"], input=texts)
        return [
            item.embedding
            for item in sorted(response.data, key=lambda item: item.index)
        ]

    def _embed_text(self, text):
        return self._embed_texts([text])[0]

    def _load_patterns(self, source_type):
        if source_type != "clean_guide":
            raise ValueError("Only clean_guide is supported / 仅支持方法卡")
        with psycopg.connect(get_db_url(), connect_timeout=5) as conn:
            rows = conn.execute(
                "SELECT chunk_id, title, content, embedding FROM knowledge_patterns"
            ).fetchall()
        return [
            {
                "chunk_id": r[0],
                "scene_type": r[1],
                "reference_text": r[2],
                "embedding": r[3],
            }
            for r in rows
        ]

    @staticmethod
    def _cosine_similarity(a, b):
        if len(a) != len(b):
            raise ValueError("Embedding dimensions differ / 向量维度不一致")
        norm = math.sqrt(sum(x * x for x in a) * sum(x * x for x in b))
        return sum(x * y for x, y in zip(a, b)) / norm if norm else 0.0


@lru_cache(maxsize=1)
def get_pattern_retriever():
    return PatternRetriever()
