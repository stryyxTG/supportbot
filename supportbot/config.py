from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _parse_admin_ids(raw: str) -> frozenset[int]:
    values: set[int] = set()
    for item in raw.replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        values.add(int(item))
    return frozenset(values)


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    database_path: Path
    support_title: str
    max_open_tickets: int = 3
    webapp_url: str = ""
    webapp_host: str = "0.0.0.0"
    webapp_port: int = 8080

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("BOT_TOKEN is required. Put it into .env")

        admins = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))
        if not admins:
            raise RuntimeError("ADMIN_IDS is required. Example: ADMIN_IDS=123,456")

        db_path = Path(os.getenv("DATABASE_PATH", "data/support.sqlite3"))
        title = os.getenv("SUPPORT_TITLE", "Техническая поддержка").strip()
        max_open = int(os.getenv("MAX_OPEN_TICKETS", "3"))
        webapp_url = os.getenv("WEBAPP_URL", "").strip()
        webapp_host = os.getenv("WEBAPP_HOST", "0.0.0.0").strip()
        webapp_port = int(os.getenv("WEBAPP_PORT", "8080"))

        return cls(
            bot_token=token,
            admin_ids=admins,
            database_path=db_path,
            support_title=title,
            max_open_tickets=max_open,
            webapp_url=webapp_url,
            webapp_host=webapp_host,
            webapp_port=webapp_port,
        )
