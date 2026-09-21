"""Explicit recipient-owned database only. / 仅连接使用者明确配置的数据库。"""

import os


def get_db_url() -> str:
    value = os.environ.get("PGDATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("Set PGDATABASE_URL / 请设置 PGDATABASE_URL")
    return value
