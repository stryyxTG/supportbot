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
        try:
            values.add(int(item))
        except ValueError as exc:
            raise RuntimeError(
                "ADMIN_IDS must contain only numeric Telegram IDs. "
                "Use ADMIN_USERNAMES for @usernames."
            ) from exc
    return frozenset(values)


def normalize_username(value: str | None) -> str:
    return (value or "").strip().removeprefix("@").lower()


def _parse_admin_usernames(raw: str) -> frozenset[str]:
    return frozenset(
        username
        for username in (normalize_username(item) for item in raw.replace(";", ",").split(","))
        if username
    )


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    admin_usernames: frozenset[str]
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
        admin_usernames = _parse_admin_usernames(os.getenv("ADMIN_USERNAMES", ""))
        if not admins and not admin_usernames:
            raise RuntimeError(
                "ADMIN_IDS or ADMIN_USERNAMES is required. "
                "Examples: ADMIN_IDS=123,456 or ADMIN_USERNAMES=user1,user2"
            )

        db_path = Path(os.getenv("DATABASE_PATH", "data/support.sqlite3"))
        title = os.getenv("SUPPORT_TITLE", "Техническая поддержка").strip()
        max_open = int(os.getenv("MAX_OPEN_TICKETS", "3"))
        webapp_url = os.getenv("WEBAPP_URL", "").strip()
        webapp_host = os.getenv("WEBAPP_HOST", "0.0.0.0").strip()
        webapp_port = int(os.getenv("WEBAPP_PORT", "8080"))

        return cls(
            bot_token=token,
            admin_ids=admins,
            admin_usernames=admin_usernames,
            database_path=db_path,
            support_title=title,
            max_open_tickets=max_open,
            webapp_url=webapp_url,
            webapp_host=webapp_host,
            webapp_port=webapp_port,
        )
