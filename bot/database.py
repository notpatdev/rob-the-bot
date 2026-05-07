from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite


@dataclass(frozen=True)
class EventSubTotalRow:
    user_id: int
    total_usd: float
    send_count: int


@dataclass(frozen=True)
class EventDommeTotalRow:
    user_id: int
    total_usd: float
    send_count: int


@dataclass(frozen=True)
class EventDommeRegistration:
    user_id: int
    throne_url: str
    registered_at: str

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "EventDommeRegistration":
        return cls(
            user_id=int(row["user_id"]),
            throne_url=row["throne_url"],
            registered_at=row["registered_at"],
        )


@dataclass(frozen=True)
class EventSubRegistration:
    user_id: int
    sub_name: str
    registered_at: str

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "EventSubRegistration":
        return cls(
            user_id=int(row["user_id"]),
            sub_name=row["sub_name"],
            registered_at=row["registered_at"],
        )


@dataclass(frozen=True)
class EventState:
    is_active: bool
    starts_at: str | None
    ends_at: str | None
    ended_at: str | None
    started_by: int | None
    ended_by: int | None

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "EventState":
        return cls(
            is_active=bool(row["is_active"]),
            starts_at=row["starts_at"],
            ends_at=row["ends_at"],
            ended_at=row["ended_at"],
            started_by=int(row["started_by"]) if row["started_by"] is not None else None,
            ended_by=int(row["ended_by"]) if row["ended_by"] is not None else None,
        )


@dataclass(frozen=True)
class EventSend:
    id: int
    domme_user_id: int
    sub_name: str | None
    claimed_sub_user_id: int | None
    amount_usd: float
    item_name: str | None
    item_image_url: str | None
    logged_by: int
    sent_at: str
    external_id: str | None
    is_private: bool
    seeded: bool

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "EventSend":
        return cls(
            id=int(row["id"]),
            domme_user_id=int(row["domme_user_id"]),
            sub_name=row["sub_name"],
            claimed_sub_user_id=int(row["claimed_sub_user_id"]) if row["claimed_sub_user_id"] is not None else None,
            amount_usd=float(row["amount_usd"]),
            item_name=row["item_name"],
            item_image_url=row["item_image_url"],
            logged_by=int(row["logged_by"]),
            sent_at=row["sent_at"],
            external_id=row["external_id"],
            is_private=bool(row["is_private"]),
            seeded=bool(row["seeded"]),
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()



class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._connection: aiosqlite.Connection | None = None

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("Database has not been initialized")
        return self._connection

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self.path)
        self._connection.row_factory = aiosqlite.Row
        await self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            CREATE TABLE IF NOT EXISTS event_messages (
                message_key TEXT PRIMARY KEY,
                message_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS event_state (
                event_key TEXT PRIMARY KEY,
                is_active INTEGER NOT NULL DEFAULT 0,
                starts_at TEXT,
                ends_at TEXT,
                ended_at TEXT,
                started_by INTEGER,
                ended_by INTEGER
            );

            CREATE TABLE IF NOT EXISTS event_dommes (
                user_id INTEGER PRIMARY KEY,
                throne_url TEXT NOT NULL,
                registered_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS event_subs (
                user_id INTEGER PRIMARY KEY,
                sub_name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                registered_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS event_sends (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domme_user_id INTEGER NOT NULL,
                sub_name TEXT COLLATE NOCASE,
                claimed_sub_user_id INTEGER,
                amount_usd REAL NOT NULL,
                item_name TEXT,
                item_image_url TEXT,
                logged_by INTEGER NOT NULL,
                sent_at TEXT NOT NULL,
                external_id TEXT,
                is_private INTEGER NOT NULL DEFAULT 0,
                seeded INTEGER NOT NULL DEFAULT 0
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_event_sends_external_id
            ON event_sends(external_id)
            WHERE external_id IS NOT NULL;

            CREATE INDEX IF NOT EXISTS idx_event_sends_domme
            ON event_sends(domme_user_id);

            CREATE INDEX IF NOT EXISTS idx_event_sends_sub
            ON event_sends(sub_name);
            """
        )
        await self.connection.commit()

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def get_event_sub_totals(
        self,
        *,
        limit: int = 10,
        offset: int = 0,
    ) -> list[EventSubTotalRow]:
        async with self.connection.execute(
            """
            SELECT
                claimed_sub_user_id AS user_id,
                SUM(CASE WHEN is_private = 0 THEN amount_usd ELSE 0 END) AS total_usd,
                COUNT(*) AS send_count
            FROM event_sends
            WHERE claimed_sub_user_id IS NOT NULL
            GROUP BY claimed_sub_user_id
            ORDER BY total_usd DESC, send_count DESC, claimed_sub_user_id ASC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            EventSubTotalRow(
                user_id=int(row["user_id"]),
                total_usd=float(row["total_usd"] or 0.0),
                send_count=int(row["send_count"]),
            )
            for row in rows
        ]

    async def save_event_domme(
        self,
        *,
        user_id: int,
        throne_url: str,
    ) -> None:
        async with self.connection.execute(
            """
            INSERT INTO event_dommes (user_id, throne_url, registered_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                throne_url = excluded.throne_url,
                registered_at = event_dommes.registered_at
            """,
            (user_id, throne_url, _utc_now()),
        ):
            pass
        await self.connection.commit()

    async def get_all_event_dommes(self) -> list[EventDommeRegistration]:
        async with self.connection.execute(
            """
            SELECT user_id, throne_url, registered_at
            FROM event_dommes
            ORDER BY registered_at ASC
            """,
        ) as cursor:
            rows = await cursor.fetchall()
        return [EventDommeRegistration.from_row(row) for row in rows]

    async def save_event_sub(
        self,
        *,
        user_id: int,
        sub_name: str,
    ) -> None:
        async with self.connection.execute(
            """
            INSERT INTO event_subs (user_id, sub_name, registered_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                sub_name = excluded.sub_name,
                registered_at = event_subs.registered_at
            """,
            (user_id, sub_name, _utc_now()),
        ):
            pass
        await self.connection.commit()
        await self.connection.execute(
            """
            UPDATE event_sends
            SET claimed_sub_user_id = ?
            WHERE sub_name = ? COLLATE NOCASE
            AND claimed_sub_user_id IS NULL
            """,
            (user_id, sub_name),
        )
        await self.connection.commit()

    async def get_event_sub_by_name(self, *, sub_name: str) -> EventSubRegistration | None:
        async with self.connection.execute(
            """
            SELECT user_id, sub_name, registered_at
            FROM event_subs
            WHERE sub_name = ? COLLATE NOCASE
            """,
            (sub_name,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return EventSubRegistration.from_row(row)

    async def count_event_ranked_subs(self) -> int:
        async with self.connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM (
                SELECT claimed_sub_user_id
                FROM event_sends
                WHERE claimed_sub_user_id IS NOT NULL
                GROUP BY claimed_sub_user_id
            )
            """
        ) as cursor:
            row = await cursor.fetchone()
        return int(row["count"]) if row is not None else 0

    async def get_event_sub_rank(self, *, user_id: int) -> int | None:
        async with self.connection.execute(
            """
            SELECT rank FROM (
                SELECT
                    claimed_sub_user_id AS user_id,
                    ROW_NUMBER() OVER (
                        ORDER BY
                            SUM(CASE WHEN is_private = 0 THEN amount_usd ELSE 0 END) DESC,
                            COUNT(*) DESC,
                            claimed_sub_user_id ASC
                    ) AS rank
                FROM event_sends
                WHERE claimed_sub_user_id IS NOT NULL
                GROUP BY claimed_sub_user_id
            ) ranked
            WHERE user_id = ?
            """,
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return int(row["rank"])

    async def get_event_unclaimed_total(self) -> float:
        async with self.connection.execute(
            """
            SELECT COALESCE(SUM(CASE WHEN is_private = 0 THEN amount_usd ELSE 0 END), 0) AS total_usd
            FROM event_sends
            WHERE claimed_sub_user_id IS NULL
            """
        ) as cursor:
            row = await cursor.fetchone()
        return float(row["total_usd"]) if row is not None else 0.0

    async def get_event_domme_totals(self) -> list[EventDommeTotalRow]:
        async with self.connection.execute(
            """
            SELECT
                domme_user_id AS user_id,
                SUM(CASE WHEN is_private = 0 THEN amount_usd ELSE 0 END) AS total_usd,
                COUNT(*) AS send_count
            FROM event_sends
            GROUP BY domme_user_id
            ORDER BY total_usd DESC, send_count DESC, domme_user_id ASC
            """
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            EventDommeTotalRow(
                user_id=int(row["user_id"]),
                total_usd=float(row["total_usd"] or 0.0),
                send_count=int(row["send_count"]),
            )
            for row in rows
        ]

    async def get_event_domme_total(self, *, user_id: int) -> EventDommeTotalRow:
        async with self.connection.execute(
            """
            SELECT
                domme_user_id AS user_id,
                COALESCE(SUM(CASE WHEN is_private = 0 THEN amount_usd ELSE 0 END), 0) AS total_usd,
                COUNT(*) AS send_count
            FROM event_sends
            WHERE domme_user_id = ?
            GROUP BY domme_user_id
            """,
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return EventDommeTotalRow(user_id=user_id, total_usd=0.0, send_count=0)
        return EventDommeTotalRow(
            user_id=int(row["user_id"]),
            total_usd=float(row["total_usd"] or 0.0),
            send_count=int(row["send_count"]),
        )

    async def get_event_message(self, *, message_key: str) -> tuple[int, int] | None:
        async with self.connection.execute(
            "SELECT message_id, channel_id FROM event_messages WHERE message_key = ?",
            (message_key,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return int(row["message_id"]), int(row["channel_id"])

    async def upsert_event_message(
        self,
        *,
        message_key: str,
        message_id: int,
        channel_id: int,
    ) -> None:
        async with self.connection.execute(
            """
            INSERT INTO event_messages (message_key, message_id, channel_id)
            VALUES (?, ?, ?)
            ON CONFLICT(message_key) DO UPDATE SET
                message_id = excluded.message_id,
                channel_id = excluded.channel_id
            """,
            (message_key, message_id, channel_id),
        ):
            pass
        await self.connection.commit()

    async def get_event_state(self) -> EventState:
        async with self.connection.execute(
            """
            SELECT is_active, starts_at, ends_at, ended_at, started_by, ended_by
            FROM event_state
            WHERE event_key = 'default'
            """,
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return EventState(
                is_active=False,
                starts_at=None,
                ends_at=None,
                ended_at=None,
                started_by=None,
                ended_by=None,
            )
        return EventState.from_row(row)

    async def start_event(
        self,
        *,
        ends_at: str,
        started_by: int,
    ) -> EventState:
        starts_at = _utc_now()
        async with self.connection.execute(
            """
            INSERT INTO event_state (
                event_key,
                is_active,
                starts_at,
                ends_at,
                ended_at,
                started_by,
                ended_by
            )
            VALUES ('default', 1, ?, ?, NULL, ?, NULL)
            ON CONFLICT(event_key) DO UPDATE SET
                is_active = 1,
                starts_at = excluded.starts_at,
                ends_at = excluded.ends_at,
                ended_at = NULL,
                started_by = excluded.started_by,
                ended_by = NULL
            """,
            (starts_at, ends_at, started_by),
        ):
            pass
        await self.connection.commit()
        return await self.get_event_state()

    async def end_event(
        self,
        *,
        ended_by: int | None,
    ) -> EventState:
        ended_at = _utc_now()
        async with self.connection.execute(
            """
            INSERT INTO event_state (
                event_key,
                is_active,
                starts_at,
                ends_at,
                ended_at,
                started_by,
                ended_by
            )
            VALUES ('default', 0, NULL, NULL, ?, NULL, ?)
            ON CONFLICT(event_key) DO UPDATE SET
                is_active = 0,
                ended_at = excluded.ended_at,
                ended_by = excluded.ended_by
            """,
            (ended_at, ended_by),
        ):
            pass
        await self.connection.commit()
        return await self.get_event_state()

    async def log_event_send(
        self,
        *,
        domme_user_id: int,
        sub_name: str | None,
        amount_usd: float,
        item_name: str | None,
        item_image_url: str | None,
        logged_by: int,
        external_id: str | None = None,
        is_private: bool = False,
        seeded: bool = False,
        sent_at: str | None = None,
    ) -> int | None:
        if external_id:
            async with self.connection.execute(
                "SELECT id FROM event_sends WHERE external_id = ?",
                (external_id,),
            ) as cursor:
                existing = await cursor.fetchone()
            if existing is not None:
                return None

        claimed_sub_user_id: int | None = None
        if sub_name:
            sub = await self.get_event_sub_by_name(sub_name=sub_name)
            if sub is not None:
                claimed_sub_user_id = sub.user_id

        async with self.connection.execute(
            """
            INSERT INTO event_sends (
                domme_user_id,
                sub_name,
                claimed_sub_user_id,
                amount_usd,
                item_name,
                item_image_url,
                logged_by,
                sent_at,
                external_id,
                is_private,
                seeded
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                domme_user_id,
                sub_name,
                claimed_sub_user_id,
                amount_usd,
                item_name,
                item_image_url,
                logged_by,
                sent_at or _utc_now(),
                external_id,
                int(bool(is_private)),
                int(bool(seeded)),
            ),
        ) as cursor:
            send_id = int(cursor.lastrowid)
        await self.connection.commit()
        return send_id

    async def get_event_send(self, *, send_id: int) -> EventSend | None:
        async with self.connection.execute(
            "SELECT * FROM event_sends WHERE id = ?",
            (send_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return EventSend.from_row(row)

    async def get_known_event_external_ids_for_domme(
        self,
        *,
        domme_user_id: int,
    ) -> set[str]:
        async with self.connection.execute(
            """
            SELECT external_id
            FROM event_sends
            WHERE domme_user_id = ? AND external_id IS NOT NULL
            """,
            (domme_user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return {row["external_id"] for row in rows}

    async def has_any_event_sends_for_domme(self, *, domme_user_id: int) -> bool:
        async with self.connection.execute(
            "SELECT 1 FROM event_sends WHERE domme_user_id = ? LIMIT 1",
            (domme_user_id,),
        ) as cursor:
            return await cursor.fetchone() is not None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
