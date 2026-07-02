from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import aiosqlite

from supportbot.texts import ACTIVE_STATUSES


def _row_to_dict(row: aiosqlite.Row | None) -> dict | None:
    return None if row is None else dict(row)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = await aiosqlite.connect(self.path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        try:
            yield db
            await db.commit()
        finally:
            await db.close()

    async def init(self) -> None:
        async with self.connect() as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tg_id INTEGER NOT NULL UNIQUE,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    is_blocked INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    public_id TEXT UNIQUE,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    status TEXT NOT NULL DEFAULT 'new',
                    priority TEXT NOT NULL DEFAULT 'normal',
                    assigned_admin_id INTEGER,
                    admin_unread INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_message_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    closed_at TEXT,
                    close_reason TEXT
                );

                CREATE TABLE IF NOT EXISTS ticket_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                    sender_role TEXT NOT NULL,
                    sender_tg_id INTEGER,
                    body TEXT,
                    content_type TEXT NOT NULL,
                    file_id TEXT,
                    telegram_message_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS ticket_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                    actor_role TEXT NOT NULL,
                    actor_tg_id INTEGER,
                    event_type TEXT NOT NULL,
                    payload TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_tickets_user_status
                    ON tickets(user_id, status, last_message_at);
                CREATE INDEX IF NOT EXISTS idx_tickets_assigned_status
                    ON tickets(assigned_admin_id, status, last_message_at);
                CREATE INDEX IF NOT EXISTS idx_messages_ticket_created
                    ON ticket_messages(ticket_id, created_at);
                """
            )
            cursor = await db.execute("PRAGMA table_info(tickets)")
            ticket_columns = {row["name"] for row in await cursor.fetchall()}
            if "admin_unread" not in ticket_columns:
                await db.execute(
                    "ALTER TABLE tickets ADD COLUMN admin_unread INTEGER NOT NULL DEFAULT 0"
                )
            await db.execute(
                """
                UPDATE tickets
                SET public_id = CAST(id AS TEXT)
                WHERE public_id IS NULL OR public_id LIKE 'SUP-%'
                """
            )

    async def upsert_user(self, tg_user: Any) -> dict:
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO users (tg_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tg_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    last_seen_at = CURRENT_TIMESTAMP
                """,
                (
                    tg_user.id,
                    tg_user.username,
                    tg_user.first_name,
                    tg_user.last_name,
                ),
            )
            cursor = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_user.id,))
            return dict(await cursor.fetchone())

    async def get_user_by_tg_id(self, tg_id: int) -> dict | None:
        async with self.connect() as db:
            cursor = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
            return _row_to_dict(await cursor.fetchone())

    async def list_users_by_usernames(self, usernames: set[str] | frozenset[str]) -> list[dict]:
        if not usernames:
            return []
        placeholders = ",".join("?" for _ in usernames)
        async with self.connect() as db:
            cursor = await db.execute(
                f"""
                SELECT *
                FROM users
                WHERE lower(username) IN ({placeholders})
                """,
                tuple(usernames),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def create_ticket(self, user_id: int) -> dict:
        async with self.connect() as db:
            cursor = await db.execute(
                "INSERT INTO tickets (user_id) VALUES (?) RETURNING *",
                (user_id,),
            )
            ticket = dict(await cursor.fetchone())
            public_id = str(ticket["id"])
            await db.execute(
                "UPDATE tickets SET public_id = ? WHERE id = ?",
                (public_id, ticket["id"]),
            )
            ticket["public_id"] = public_id
            await self._add_event_in_conn(
                db,
                ticket["id"],
                "system",
                None,
                "ticket_created",
                {},
            )
            return ticket

    async def add_message(
        self,
        ticket_id: int,
        sender_role: str,
        sender_tg_id: int | None,
        body: str,
        content_type: str,
        file_id: str | None,
        telegram_message_id: int | None,
    ) -> dict:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                INSERT INTO ticket_messages (
                    ticket_id, sender_role, sender_tg_id, body, content_type,
                    file_id, telegram_message_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                RETURNING *
                """,
                (
                    ticket_id,
                    sender_role,
                    sender_tg_id,
                    body,
                    content_type,
                    file_id,
                    telegram_message_id,
                ),
            )
            message = dict(await cursor.fetchone())
            admin_unread = 1 if sender_role == "user" else 0
            await db.execute(
                """
                UPDATE tickets
                SET last_message_at = CURRENT_TIMESTAMP,
                    admin_unread = ?
                WHERE id = ?
                """,
                (admin_unread, ticket_id),
            )
            return message

    async def set_status(
        self,
        ticket_id: int,
        status: str,
        actor_role: str,
        actor_tg_id: int | None,
        event_type: str,
        payload: dict | None = None,
    ) -> dict | None:
        async with self.connect() as db:
            if status == "closed":
                status_sql = "status = ?, closed_at = CURRENT_TIMESTAMP"
            elif status in ACTIVE_STATUSES:
                status_sql = "status = ?, closed_at = NULL, close_reason = NULL"
            else:
                status_sql = "status = ?"
            await db.execute(
                f"UPDATE tickets SET {status_sql} WHERE id = ?",
                (status, ticket_id),
            )
            await self._add_event_in_conn(
                db, ticket_id, actor_role, actor_tg_id, event_type, payload or {}
            )
            cursor = await db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
            return _row_to_dict(await cursor.fetchone())

    async def assign_ticket(self, ticket_id: int, admin_id: int) -> dict | None:
        async with self.connect() as db:
            await db.execute(
                """
                UPDATE tickets
                SET assigned_admin_id = ?, status = 'in_progress', admin_unread = 0
                WHERE id = ?
                """,
                (admin_id, ticket_id),
            )
            await self._add_event_in_conn(
                db,
                ticket_id,
                "admin",
                admin_id,
                "ticket_assigned",
                {"admin_id": admin_id},
            )
            cursor = await db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
            return _row_to_dict(await cursor.fetchone())

    async def claim_ticket(self, ticket_id: int, admin_id: int) -> dict | None:
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        async with self.connect() as db:
            cursor = await db.execute(
                f"""
                UPDATE tickets
                SET assigned_admin_id = ?, status = 'in_progress', admin_unread = 0
                WHERE id = ?
                    AND status IN ({placeholders})
                    AND (assigned_admin_id IS NULL OR assigned_admin_id = ?)
                RETURNING *
                """,
                (admin_id, ticket_id, *ACTIVE_STATUSES, admin_id),
            )
            ticket = await cursor.fetchone()
            if ticket is None:
                return None

            ticket_dict = dict(ticket)
            await self._add_event_in_conn(
                db,
                ticket_id,
                "admin",
                admin_id,
                "ticket_claimed",
                {"admin_id": admin_id},
            )
            return ticket_dict

    async def get_ticket(self, ticket_id: int) -> dict | None:
        async with self.connect() as db:
            cursor = await db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
            return _row_to_dict(await cursor.fetchone())

    async def mark_ticket_read(self, ticket_id: int) -> None:
        async with self.connect() as db:
            await db.execute(
                "UPDATE tickets SET admin_unread = 0 WHERE id = ?",
                (ticket_id,),
            )

    async def get_ticket_with_user(self, ticket_id: int) -> tuple[dict, dict] | None:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT
                    t.*,
                    u.id AS u_id,
                    u.tg_id AS u_tg_id,
                    u.username AS u_username,
                    u.first_name AS u_first_name,
                    u.last_name AS u_last_name,
                    u.is_blocked AS u_is_blocked
                FROM tickets t
                JOIN users u ON u.id = t.user_id
                WHERE t.id = ?
                """,
                (ticket_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            data = dict(row)
            ticket = {k: data[k] for k in data if not k.startswith("u_")}
            user = {
                "id": data["u_id"],
                "tg_id": data["u_tg_id"],
                "username": data["u_username"],
                "first_name": data["u_first_name"],
                "last_name": data["u_last_name"],
                "is_blocked": data["u_is_blocked"],
            }
            return ticket, user

    async def list_user_tickets(
        self,
        tg_id: int,
        limit: int = 7,
        offset: int = 0,
    ) -> list[dict]:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT t.*
                FROM tickets t
                JOIN users u ON u.id = t.user_id
                WHERE u.tg_id = ?
                ORDER BY t.last_message_at DESC
                LIMIT ? OFFSET ?
                """,
                (tg_id, limit, offset),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def count_user_tickets(self, tg_id: int) -> int:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*) AS count
                FROM tickets t
                JOIN users u ON u.id = t.user_id
                WHERE u.tg_id = ?
                """,
                (tg_id,),
            )
            row = await cursor.fetchone()
            return int(row["count"])

    async def count_user_active_tickets(self, tg_id: int) -> int:
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        async with self.connect() as db:
            cursor = await db.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM tickets t
                JOIN users u ON u.id = t.user_id
                WHERE u.tg_id = ? AND t.status IN ({placeholders})
                """,
                (tg_id, *ACTIVE_STATUSES),
            )
            row = await cursor.fetchone()
            return int(row["count"])

    async def get_single_active_ticket(self, tg_id: int) -> dict | None:
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        async with self.connect() as db:
            cursor = await db.execute(
                f"""
                SELECT t.*
                FROM tickets t
                JOIN users u ON u.id = t.user_id
                WHERE u.tg_id = ? AND t.status IN ({placeholders})
                ORDER BY t.last_message_at DESC
                LIMIT 2
                """,
                (tg_id, *ACTIVE_STATUSES),
            )
            rows = [dict(row) for row in await cursor.fetchall()]
            return rows[0] if len(rows) == 1 else None

    async def list_queue(self, limit: int = 20) -> list[dict]:
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        async with self.connect() as db:
            cursor = await db.execute(
                f"""
                SELECT *
                FROM tickets
                WHERE status IN ({placeholders})
                ORDER BY
                    CASE WHEN assigned_admin_id IS NULL THEN 0 ELSE 1 END,
                    last_message_at ASC
                LIMIT ?
                """,
                (*ACTIVE_STATUSES, limit),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def find_ticket(self, query: str) -> dict | None:
        normalized = query.strip().upper()
        if not normalized:
            return None
        if normalized.startswith("#"):
            normalized = normalized[1:].strip()
        if normalized.startswith("№"):
            normalized = normalized[1:].strip()
        if normalized.isdigit():
            normalized = str(int(normalized))
        elif normalized.startswith("SUP-") and normalized[4:].isdigit():
            normalized = str(int(normalized[4:]))

        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT * FROM tickets WHERE public_id = ?",
                (normalized,),
            )
            return _row_to_dict(await cursor.fetchone())

    async def list_messages(self, ticket_id: int, limit: int = 10) -> list[dict]:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT *
                FROM ticket_messages
                WHERE ticket_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (ticket_id, limit),
            )
            rows = [dict(row) for row in await cursor.fetchall()]
            return list(reversed(rows))

    async def get_message(self, message_id: int) -> dict | None:
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT * FROM ticket_messages WHERE id = ?",
                (message_id,),
            )
            return _row_to_dict(await cursor.fetchone())

    def _admin_section_condition(self, section: str) -> tuple[str, tuple]:
        if section == "closed":
            return "t.status IN ('closed', 'resolved')", ()
        if section == "active":
            return "t.status IN ('in_progress', 'waiting_user')", ()
        return "t.status IN ('new', 'waiting_admin')", ()

    async def list_admin_section(
        self,
        section: str,
        limit: int = 30,
        offset: int = 0,
    ) -> list[dict]:
        condition, params = self._admin_section_condition(section)
        unread_order = "t.admin_unread DESC," if section == "active" else ""
        async with self.connect() as db:
            cursor = await db.execute(
                f"""
                SELECT
                    t.*,
                    u.tg_id AS user_tg_id,
                    u.username AS username,
                    u.first_name AS first_name,
                    u.last_name AS last_name,
                    m.body AS last_body,
                    m.content_type AS last_content_type
                FROM tickets t
                JOIN users u ON u.id = t.user_id
                LEFT JOIN ticket_messages m ON m.id = (
                    SELECT id
                    FROM ticket_messages
                    WHERE ticket_id = t.id
                    ORDER BY id DESC
                    LIMIT 1
                )
                WHERE {condition}
                ORDER BY {unread_order} t.last_message_at DESC
                LIMIT ? OFFSET ?
                """,
                (*params, limit, offset),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def count_admin_section(self, section: str) -> int:
        condition, params = self._admin_section_condition(section)
        async with self.connect() as db:
            cursor = await db.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM tickets t
                WHERE {condition}
                """,
                params,
            )
            row = await cursor.fetchone()
            return int(row["count"])

    async def count_active_unread(self) -> int:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*) AS count
                FROM tickets
                WHERE status IN ('in_progress', 'waiting_user')
                  AND admin_unread = 1
                """
            )
            row = await cursor.fetchone()
            return int(row["count"])

    async def clear_closed_tickets(self) -> int:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                DELETE FROM tickets
                WHERE status IN ('closed', 'resolved')
                RETURNING id
                """
            )
            rows = await cursor.fetchall()
            return len(rows)

    async def list_ticket_messages(
        self,
        ticket_id: int,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT *
                FROM ticket_messages
                WHERE ticket_id = ?
                ORDER BY id ASC
                LIMIT ? OFFSET ?
                """,
                (ticket_id, limit, offset),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def list_ticket_messages_after(
        self,
        ticket_id: int,
        after_message_id: int,
        limit: int = 100,
    ) -> list[dict]:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT *
                FROM ticket_messages
                WHERE ticket_id = ? AND id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (ticket_id, after_message_id, limit),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def admin_section_counts(self) -> dict:
        return {
            "new": await self.count_admin_section("new"),
            "active": await self.count_admin_section("active"),
            "active_unread": await self.count_active_unread(),
            "closed": await self.count_admin_section("closed"),
        }

    async def stats(self) -> dict:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM tickets
                GROUP BY status
                """
            )
            by_status = {row["status"]: row["count"] for row in await cursor.fetchall()}
            cursor = await db.execute(
                "SELECT COUNT(*) AS count FROM tickets WHERE date(created_at) = date('now')"
            )
            today = int((await cursor.fetchone())["count"])
            cursor = await db.execute("SELECT COUNT(*) AS count FROM users")
            users = int((await cursor.fetchone())["count"])
            return {"by_status": by_status, "today": today, "users": users}

    async def _add_event_in_conn(
        self,
        db: aiosqlite.Connection,
        ticket_id: int,
        actor_role: str,
        actor_tg_id: int | None,
        event_type: str,
        payload: dict,
    ) -> None:
        await db.execute(
            """
            INSERT INTO ticket_events (
                ticket_id, actor_role, actor_tg_id, event_type, payload
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (ticket_id, actor_role, actor_tg_id, event_type, json.dumps(payload)),
        )
