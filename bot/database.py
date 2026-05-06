from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite


@dataclass(frozen=True)
class VerificationRequest:
    id: int
    user_id: int
    guild_id: int
    username: str
    verification_type: str | None
    verification_value: str | None
    selected_role: str | None
    status: str
    submitted_at: str
    reviewed_at: str | None
    reviewed_by: int | None
    log_message_id: int | None
    log_channel_id: int | None

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "VerificationRequest":
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            guild_id=row["guild_id"],
            username=row["username"],
            verification_type=row["verification_type"],
            verification_value=row["verification_value"],
            selected_role=row["selected_role"],
            status=row["status"],
            submitted_at=row["submitted_at"],
            reviewed_at=row["reviewed_at"],
            reviewed_by=row["reviewed_by"],
            log_message_id=row["log_message_id"],
            log_channel_id=row["log_channel_id"],
        )


@dataclass(frozen=True)
class DommeProfile:
    user_id: int
    name: str | None
    honorific: str | None
    pronouns: str | None
    age: str | None
    tribute_price: str | None
    throne: str | None
    tribute_link: str | None
    payment_link1: str | None
    payment_link2: str | None
    payment_link3: str | None
    payment_link4: str | None
    content_link1: str | None
    content_link2: str | None
    content_link3: str | None
    content_link4: str | None
    profile_color: int
    throne_tracking_enabled: bool
    kinks: str | None
    limits: str | None
    created_at: str

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "DommeProfile":
        return cls(
            user_id=row["user_id"],
            name=row["name"],
            honorific=row["honorific"],
            pronouns=row["pronouns"],
            age=row["age"],
            tribute_price=row["tribute_price"],
            throne=row["throne"],
            tribute_link=row["tribute_link"],
            payment_link1=row["payment_link1"],
            payment_link2=row["payment_link2"],
            payment_link3=row["payment_link3"],
            payment_link4=row["payment_link4"],
            content_link1=row["content_link1"],
            content_link2=row["content_link2"],
            content_link3=row["content_link3"],
            content_link4=row["content_link4"],
            profile_color=row["profile_color"] or 16737714,
            throne_tracking_enabled=bool(row["throne_tracking_enabled"]),
            kinks=row["kinks"],
            limits=row["limits"],
            created_at=row["created_at"],
        )


@dataclass(frozen=True)
class SubProfile:
    user_id: int
    throne_name: str | None
    name: str | None
    pronouns: str | None
    age: str | None
    profile_color: int
    kinks: str | None
    limits: str | None
    owned_by_domme_user_id: int | None
    created_at: str

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "SubProfile":
        return cls(
            user_id=row["user_id"],
            throne_name=row["throne_name"],
            name=row["name"],
            pronouns=row["pronouns"],
            age=row["age"],
            profile_color=int(row["profile_color"]) if row["profile_color"] else 2762042,
            kinks=row["kinks"],
            limits=row["limits"],
            owned_by_domme_user_id=int(row["owned_by_domme_user_id"]) if row["owned_by_domme_user_id"] else None,
            created_at=row["created_at"],
        )


@dataclass(frozen=True)
class ThroneSend:
    id: int
    domme_user_id: int
    sub_throne_name: str | None
    claimed_sub_user_id: int | None
    amount_usd: float
    item_name: str | None
    item_image_url: str | None
    logged_by: int
    sent_at: str
    external_id: str | None = None
    is_private: bool = False
    seeded: bool = False

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "ThroneSend":
        return cls(
            id=row["id"],
            domme_user_id=row["domme_user_id"],
            sub_throne_name=row["sub_throne_name"],
            claimed_sub_user_id=row["claimed_sub_user_id"],
            amount_usd=row["amount_usd"],
            item_name=row["item_name"],
            item_image_url=row["item_image_url"],
            logged_by=row["logged_by"],
            sent_at=row["sent_at"],
            external_id=row["external_id"],
            is_private=bool(row["is_private"]),
            seeded=bool(row["seeded"]),
        )


@dataclass(frozen=True)
class LeaderboardRow:
    """Pre-aggregated row used by the server leaderboard embed."""
    sub_throne_name: str | None
    claimed_sub_user_id: int | None
    domme_user_id: int
    total_usd: float
    send_count: int


@dataclass(frozen=True)
class ReactionRoleBinding:
    id: int
    guild_id: int
    channel_id: int
    message_id: int
    emoji_key: str
    emoji_display: str
    role_id: int
    created_by: int
    created_at: str

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "ReactionRoleBinding":
        return cls(
            id=row["id"],
            guild_id=row["guild_id"],
            channel_id=row["channel_id"],
            message_id=row["message_id"],
            emoji_key=row["emoji_key"],
            emoji_display=row["emoji_display"],
            role_id=row["role_id"],
            created_by=row["created_by"],
            created_at=row["created_at"],
        )


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
            CREATE TABLE IF NOT EXISTS verification_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                verification_type TEXT,
                verification_value TEXT,
                selected_role TEXT,
                status TEXT NOT NULL CHECK (
                    status IN (
                        'pending',
                        'approved',
                        'denied_underage',
                        'denied_invalid',
                        'expired'
                    )
                ),
                submitted_at TEXT NOT NULL,
                reviewed_at TEXT,
                reviewed_by INTEGER,
                log_message_id INTEGER,
                log_channel_id INTEGER
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_verification_one_pending
            ON verification_requests(user_id, guild_id)
            WHERE status = 'pending';

            CREATE INDEX IF NOT EXISTS idx_verification_user_guild
            ON verification_requests(user_id, guild_id);

            CREATE INDEX IF NOT EXISTS idx_verification_status
            ON verification_requests(status);

            CREATE TABLE IF NOT EXISTS domme_profiles (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                honorific TEXT,
                pronouns TEXT,
                age TEXT,
                tribute_price TEXT,
                throne TEXT,
                tribute_link TEXT,
                payment_link1 TEXT,
                payment_link2 TEXT,
                payment_link3 TEXT,
                payment_link4 TEXT,
                content_link1 TEXT,
                content_link2 TEXT,
                content_link3 TEXT,
                content_link4 TEXT,
                profile_color INTEGER NOT NULL DEFAULT 16737714,
                throne_tracking_enabled INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sub_profiles (
                user_id INTEGER PRIMARY KEY,
                throne_name TEXT COLLATE NOCASE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS throne_sends (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domme_user_id INTEGER NOT NULL,
                sub_throne_name TEXT COLLATE NOCASE,
                claimed_sub_user_id INTEGER,
                amount_usd REAL NOT NULL,
                item_name TEXT,
                item_image_url TEXT,
                logged_by INTEGER NOT NULL,
                sent_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_throne_sends_domme
            ON throne_sends(domme_user_id);

            CREATE INDEX IF NOT EXISTS idx_throne_sends_sub
            ON throne_sends(sub_throne_name);

            CREATE TABLE IF NOT EXISTS leaderboard_messages (
                guild_id INTEGER PRIMARY KEY,
                message_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reaction_role_bindings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                emoji_key TEXT NOT NULL,
                emoji_display TEXT NOT NULL,
                role_id INTEGER NOT NULL,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(message_id, emoji_key)
            );

            CREATE INDEX IF NOT EXISTS idx_reaction_role_message
            ON reaction_role_bindings(message_id);

            CREATE INDEX IF NOT EXISTS idx_reaction_role_role
            ON reaction_role_bindings(role_id);

            UPDATE verification_requests
            SET reviewed_by = NULL
            WHERE status = 'pending';
            """
        )
        await self.connection.commit()
        await self._migrate_domme_profiles()
        await self._migrate_sub_profiles()
        await self._migrate_throne_sends()
        await self._claim_sends_with_matching_sub_profiles()

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def create_request(
        self,
        *,
        user_id: int,
        guild_id: int,
        username: str,
        verification_type: str | None,
        verification_value: str | None,
        selected_role: str | None,
        status: str = "pending",
    ) -> int:
        async with self.connection.execute(
            """
            INSERT INTO verification_requests (
                user_id,
                guild_id,
                username,
                verification_type,
                verification_value,
                selected_role,
                status,
                submitted_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                guild_id,
                username,
                verification_type,
                verification_value,
                selected_role,
                status,
                _utc_now(),
            ),
        ) as cursor:
            request_id = int(cursor.lastrowid)
        await self.connection.commit()
        return request_id

    async def set_log_message(
        self,
        *,
        request_id: int,
        log_message_id: int,
        log_channel_id: int,
    ) -> None:
        async with self.connection.execute(
            """
            UPDATE verification_requests
            SET log_message_id = ?, log_channel_id = ?
            WHERE id = ?
            """,
            (log_message_id, log_channel_id, request_id),
        ):
            pass
        await self.connection.commit()

    async def claim_pending_request(self, *, request_id: int, reviewed_by: int) -> bool:
        async with self.connection.execute(
            """
            UPDATE verification_requests
            SET reviewed_by = ?
            WHERE id = ?
            AND status = 'pending'
            AND reviewed_by IS NULL
            """,
            (reviewed_by, request_id),
        ) as cursor:
            claimed = cursor.rowcount > 0
        await self.connection.commit()
        return claimed

    async def release_request_claim(self, *, request_id: int, reviewed_by: int) -> None:
        async with self.connection.execute(
            """
            UPDATE verification_requests
            SET reviewed_by = NULL
            WHERE id = ?
            AND status = 'pending'
            AND reviewed_by = ?
            """,
            (request_id, reviewed_by),
        ):
            pass
        await self.connection.commit()

    async def get_request(self, request_id: int) -> VerificationRequest | None:
        return await self._fetch_one(
            "SELECT * FROM verification_requests WHERE id = ?",
            (request_id,),
        )

    async def get_pending_request(
        self,
        *,
        user_id: int,
        guild_id: int,
    ) -> VerificationRequest | None:
        return await self._fetch_one(
            """
            SELECT *
            FROM verification_requests
            WHERE user_id = ? AND guild_id = ? AND status = 'pending'
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id, guild_id),
        )

    async def get_latest_request(
        self,
        *,
        user_id: int,
        guild_id: int,
    ) -> VerificationRequest | None:
        return await self._fetch_one(
            """
            SELECT *
            FROM verification_requests
            WHERE user_id = ? AND guild_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id, guild_id),
        )

    async def get_pending_log_requests(self) -> list[VerificationRequest]:
        async with self.connection.execute(
            """
            SELECT *
            FROM verification_requests
            WHERE status = 'pending'
            AND log_message_id IS NOT NULL
            AND log_channel_id IS NOT NULL
            ORDER BY id ASC
            """
        ) as cursor:
            rows = await cursor.fetchall()
        return [VerificationRequest.from_row(row) for row in rows]

    async def mark_reviewed(
        self,
        *,
        request_id: int,
        status: str,
        reviewed_by: int | None,
    ) -> bool:
        async with self.connection.execute(
            """
            UPDATE verification_requests
            SET status = ?, reviewed_at = ?, reviewed_by = ?
            WHERE id = ?
            AND status = 'pending'
            AND (reviewed_by IS NULL OR reviewed_by = ?)
            """,
            (status, _utc_now(), reviewed_by, request_id, reviewed_by),
        ) as cursor:
            updated = cursor.rowcount > 0
        await self.connection.commit()
        return updated

    async def _migrate_domme_profiles(self) -> None:
        """Add new columns to domme_profiles if they don't exist yet (schema migration)."""
        async with self.connection.execute("PRAGMA table_info(domme_profiles)") as cursor:
            columns = {row["name"] for row in await cursor.fetchall()}
        new_columns: dict[str, str] = {
            "tribute_link": "TEXT",
            "payment_link1": "TEXT",
            "payment_link2": "TEXT",
            "payment_link3": "TEXT",
            "payment_link4": "TEXT",
            "content_link1": "TEXT",
            "content_link2": "TEXT",
            "content_link3": "TEXT",
            "content_link4": "TEXT",
            "profile_color": "INTEGER NOT NULL DEFAULT 16737714",
            "kinks": "TEXT",
            "limits": "TEXT",
        }
        for col, col_type in new_columns.items():
            if col not in columns:
                await self.connection.execute(
                    f"ALTER TABLE domme_profiles ADD COLUMN {col} {col_type}"
                )
        await self.connection.commit()

    async def _migrate_sub_profiles(self) -> None:
        """Add new columns to sub_profiles if they don't exist yet (schema migration)."""
        async with self.connection.execute("PRAGMA table_info(sub_profiles)") as cursor:
            columns = {row["name"] for row in await cursor.fetchall()}
        new_columns: dict[str, str] = {
            "name": "TEXT",
            "pronouns": "TEXT",
            "age": "TEXT",
            "profile_color": "INTEGER NOT NULL DEFAULT 2762042",
            "kinks": "TEXT",
            "limits": "TEXT",
            "owned_by_domme_user_id": "INTEGER",
        }
        for col, col_type in new_columns.items():
            if col not in columns:
                await self.connection.execute(
                    f"ALTER TABLE sub_profiles ADD COLUMN {col} {col_type}"
                )
        await self.connection.commit()

    async def _migrate_throne_sends(self) -> None:
        """Add new columns to throne_sends if they don't exist yet (schema migration)."""
        async with self.connection.execute("PRAGMA table_info(throne_sends)") as cursor:
            columns = {row["name"] for row in await cursor.fetchall()}
        new_columns: dict[str, str] = {
            "external_id": "TEXT",
            "is_private": "INTEGER NOT NULL DEFAULT 0",
            "seeded": "INTEGER NOT NULL DEFAULT 0",
        }
        for col, col_type in new_columns.items():
            if col not in columns:
                await self.connection.execute(
                    f"ALTER TABLE throne_sends ADD COLUMN {col} {col_type}"
                )
        # Unique index on external_id (NULL values are not considered equal in SQLite,
        # so manual sends without an external_id are unaffected).
        await self.connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_throne_sends_external_id "
            "ON throne_sends(external_id) WHERE external_id IS NOT NULL"
        )
        await self.connection.commit()

    async def _claim_sends_with_matching_sub_profiles(self) -> None:
        """Auto-link unclaimed sends to sub profiles where throne_name matches."""
        await self.connection.execute(
            """
            UPDATE throne_sends
            SET claimed_sub_user_id = (
                SELECT user_id FROM sub_profiles
                WHERE LOWER(sub_profiles.throne_name) = LOWER(throne_sends.sub_throne_name)
                LIMIT 1
            )
            WHERE claimed_sub_user_id IS NULL
            AND sub_throne_name IS NOT NULL
            """
        )
        await self.connection.commit()

    async def get_domme_profile(self, *, user_id: int) -> DommeProfile | None:
        async with self.connection.execute(
            "SELECT * FROM domme_profiles WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return DommeProfile.from_row(row)

    async def save_domme_profile(
        self,
        *,
        user_id: int,
        name: str | None,
        honorific: str | None,
        pronouns: str | None,
        age: str | None,
        tribute_price: str | None,
        throne: str | None,
        tribute_link: str | None,
        payment_link1: str | None,
        payment_link2: str | None,
        payment_link3: str | None,
        payment_link4: str | None,
        content_link1: str | None,
        content_link2: str | None,
        content_link3: str | None,
        content_link4: str | None,
        profile_color: int,
        throne_tracking_enabled: bool,
        kinks: str | None,
        limits: str | None,
    ) -> None:
        async with self.connection.execute(
            """
            INSERT INTO domme_profiles (
                user_id,
                name,
                honorific,
                pronouns,
                age,
                tribute_price,
                throne,
                tribute_link,
                payment_link1,
                payment_link2,
                payment_link3,
                payment_link4,
                content_link1,
                content_link2,
                content_link3,
                content_link4,
                profile_color,
                throne_tracking_enabled,
                kinks,
                limits,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                name = excluded.name,
                honorific = excluded.honorific,
                pronouns = excluded.pronouns,
                age = excluded.age,
                tribute_price = excluded.tribute_price,
                throne = excluded.throne,
                tribute_link = excluded.tribute_link,
                payment_link1 = excluded.payment_link1,
                payment_link2 = excluded.payment_link2,
                payment_link3 = excluded.payment_link3,
                payment_link4 = excluded.payment_link4,
                content_link1 = excluded.content_link1,
                content_link2 = excluded.content_link2,
                content_link3 = excluded.content_link3,
                content_link4 = excluded.content_link4,
                profile_color = excluded.profile_color,
                throne_tracking_enabled = excluded.throne_tracking_enabled,
                kinks = excluded.kinks,
                limits = excluded.limits,
                created_at = domme_profiles.created_at
            """,
            (
                user_id,
                name,
                honorific,
                pronouns,
                age,
                tribute_price,
                throne,
                tribute_link,
                payment_link1,
                payment_link2,
                payment_link3,
                payment_link4,
                content_link1,
                content_link2,
                content_link3,
                content_link4,
                profile_color,
                int(throne_tracking_enabled),
                kinks,
                limits,
                _utc_now(),
            ),
        ):
            pass
        await self.connection.commit()

    async def delete_domme_profile(self, *, user_id: int) -> bool:
        async with self.connection.execute(
            "DELETE FROM domme_profiles WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            deleted = cursor.rowcount > 0
        await self.connection.commit()
        return deleted

    async def get_sub_profile(self, *, user_id: int) -> SubProfile | None:
        async with self.connection.execute(
            "SELECT * FROM sub_profiles WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return SubProfile.from_row(row)

    async def get_sub_profile_by_throne_name(self, *, throne_name: str) -> SubProfile | None:
        async with self.connection.execute(
            "SELECT * FROM sub_profiles WHERE throne_name = ? COLLATE NOCASE",
            (throne_name,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return SubProfile.from_row(row)

    async def save_sub_profile(
        self,
        *,
        user_id: int,
        throne_name: str | None,
        name: str | None,
        pronouns: str | None,
        age: str | None,
        profile_color: int,
        kinks: str | None,
        limits: str | None,
        owned_by_domme_user_id: int | None,
    ) -> None:
        async with self.connection.execute(
            """
            INSERT INTO sub_profiles (
                user_id, throne_name, name, pronouns, age, profile_color,
                kinks, limits, owned_by_domme_user_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                throne_name = excluded.throne_name,
                name = excluded.name,
                pronouns = excluded.pronouns,
                age = excluded.age,
                profile_color = excluded.profile_color,
                kinks = excluded.kinks,
                limits = excluded.limits,
                owned_by_domme_user_id = excluded.owned_by_domme_user_id,
                created_at = sub_profiles.created_at
            """,
            (
                user_id,
                throne_name,
                name,
                pronouns,
                age,
                profile_color,
                kinks,
                limits,
                owned_by_domme_user_id,
                _utc_now(),
            ),
        ):
            pass
        await self.connection.commit()
        # Auto-claim any matching unclaimed sends
        if throne_name:
            await self.connection.execute(
                """
                UPDATE throne_sends
                SET claimed_sub_user_id = ?
                WHERE sub_throne_name = ? COLLATE NOCASE
                AND claimed_sub_user_id IS NULL
                """,
                (user_id, throne_name),
            )
            await self.connection.commit()

    async def delete_sub_profile(self, *, user_id: int) -> bool:
        async with self.connection.execute(
            "DELETE FROM sub_profiles WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            deleted = cursor.rowcount > 0
        await self.connection.commit()
        return deleted

    async def log_throne_send(
        self,
        *,
        domme_user_id: int,
        sub_throne_name: str | None,
        amount_usd: float,
        item_name: str | None,
        item_image_url: str | None,
        logged_by: int,
        external_id: str | None = None,
        is_private: bool = False,
        seeded: bool = False,
        sent_at: str | None = None,
    ) -> int | None:
        """Insert a Throne send.

        If ``external_id`` is provided and a row with that external_id already
        exists, no insert is performed and ``None`` is returned. Otherwise the
        new row id is returned.
        """
        if external_id:
            async with self.connection.execute(
                "SELECT id FROM throne_sends WHERE external_id = ?",
                (external_id,),
            ) as cursor:
                existing = await cursor.fetchone()
            if existing is not None:
                return None

        claimed_sub_user_id: int | None = None
        if sub_throne_name:
            sub = await self.get_sub_profile_by_throne_name(throne_name=sub_throne_name)
            if sub:
                claimed_sub_user_id = sub.user_id
        async with self.connection.execute(
            """
            INSERT INTO throne_sends (
                domme_user_id,
                sub_throne_name,
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
                sub_throne_name,
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

    async def get_send(self, *, send_id: int) -> ThroneSend | None:
        async with self.connection.execute(
            "SELECT * FROM throne_sends WHERE id = ?",
            (send_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return ThroneSend.from_row(row)

    async def get_known_external_ids_for_domme(
        self, *, domme_user_id: int
    ) -> set[str]:
        async with self.connection.execute(
            """
            SELECT external_id FROM throne_sends
            WHERE domme_user_id = ? AND external_id IS NOT NULL
            """,
            (domme_user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return {row["external_id"] for row in rows}

    async def has_any_sends_for_domme(self, *, domme_user_id: int) -> bool:
        async with self.connection.execute(
            "SELECT 1 FROM throne_sends WHERE domme_user_id = ? LIMIT 1",
            (domme_user_id,),
        ) as cursor:
            return await cursor.fetchone() is not None

    async def get_sends_for_domme(self, *, domme_user_id: int) -> list[ThroneSend]:
        async with self.connection.execute(
            """
            SELECT * FROM throne_sends
            WHERE domme_user_id = ?
            ORDER BY sent_at DESC
            """,
            (domme_user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [ThroneSend.from_row(row) for row in rows]

    async def get_all_sends(self) -> list[ThroneSend]:
        async with self.connection.execute(
            "SELECT * FROM throne_sends ORDER BY sent_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
        return [ThroneSend.from_row(row) for row in rows]

    async def get_leaderboard_top_sends(self, limit: int = 25) -> list[LeaderboardRow]:
        """Return SQL-aggregated (sub, domme, total) rows sorted by total DESC.

        Aggregation is done in the database to avoid loading the full table.
        Each sub is identified by a collision-free prefixed key:
          - claimed users   → 'claimed:<user_id>'
          - named unclaimed → 'name:<throne_name>'
          - anonymous       → 'anonymous'
        MAX() is used for label columns so the result is deterministic.
        """
        async with self.connection.execute(
            """
            SELECT
                MAX(sub_throne_name) AS sub_throne_name,
                MAX(claimed_sub_user_id) AS claimed_sub_user_id,
                domme_user_id,
                SUM(amount_usd) AS total_usd,
                COUNT(*) AS send_count
            FROM throne_sends
            GROUP BY
                CASE
                    WHEN claimed_sub_user_id IS NOT NULL THEN 'claimed:' || CAST(claimed_sub_user_id AS TEXT)
                    WHEN sub_throne_name IS NOT NULL THEN 'name:' || sub_throne_name
                    ELSE 'anonymous'
                END,
                domme_user_id
            ORDER BY send_count DESC, total_usd DESC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            LeaderboardRow(
                sub_throne_name=row["sub_throne_name"],
                claimed_sub_user_id=int(row["claimed_sub_user_id"]) if row["claimed_sub_user_id"] is not None else None,
                domme_user_id=int(row["domme_user_id"]),
                total_usd=float(row["total_usd"]),
                send_count=int(row["send_count"]),
            )
            for row in rows
        ]

    async def get_leaderboard_message(self, *, guild_id: int) -> tuple[int, int] | None:
        """Return (message_id, channel_id) or None."""
        async with self.connection.execute(
            "SELECT message_id, channel_id FROM leaderboard_messages WHERE guild_id = ?",
            (guild_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return int(row["message_id"]), int(row["channel_id"])

    async def upsert_leaderboard_message(
        self,
        *,
        guild_id: int,
        message_id: int,
        channel_id: int,
    ) -> None:
        async with self.connection.execute(
            """
            INSERT INTO leaderboard_messages (guild_id, message_id, channel_id)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                message_id = excluded.message_id,
                channel_id = excluded.channel_id
            """,
            (guild_id, message_id, channel_id),
        ):
            pass
        await self.connection.commit()

    async def upsert_reaction_role_binding(
        self,
        *,
        guild_id: int,
        channel_id: int,
        message_id: int,
        emoji_key: str,
        emoji_display: str,
        role_id: int,
        created_by: int,
    ) -> None:
        async with self.connection.execute(
            """
            INSERT INTO reaction_role_bindings (
                guild_id, channel_id, message_id, emoji_key, emoji_display, role_id, created_by, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id, emoji_key) DO UPDATE SET
                guild_id = excluded.guild_id,
                channel_id = excluded.channel_id,
                emoji_display = excluded.emoji_display,
                role_id = excluded.role_id,
                created_by = excluded.created_by
            """,
            (
                guild_id,
                channel_id,
                message_id,
                emoji_key,
                emoji_display,
                role_id,
                created_by,
                _utc_now(),
            ),
        ):
            pass
        await self.connection.commit()

    async def get_reaction_role_binding(
        self,
        *,
        guild_id: int,
        message_id: int,
        emoji_key: str,
    ) -> ReactionRoleBinding | None:
        async with self.connection.execute(
            """
            SELECT *
            FROM reaction_role_bindings
            WHERE guild_id = ? AND message_id = ? AND emoji_key = ?
            LIMIT 1
            """,
            (guild_id, message_id, emoji_key),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return ReactionRoleBinding.from_row(row)

    async def get_reaction_role_bindings_for_message(
        self,
        *,
        guild_id: int,
        message_id: int,
    ) -> list[ReactionRoleBinding]:
        async with self.connection.execute(
            """
            SELECT *
            FROM reaction_role_bindings
            WHERE guild_id = ? AND message_id = ?
            ORDER BY id ASC
            """,
            (guild_id, message_id),
        ) as cursor:
            rows = await cursor.fetchall()
        return [ReactionRoleBinding.from_row(row) for row in rows]

    async def remove_reaction_role_binding(
        self,
        *,
        guild_id: int,
        message_id: int,
        emoji_key: str,
    ) -> bool:
        async with self.connection.execute(
            """
            DELETE FROM reaction_role_bindings
            WHERE guild_id = ? AND message_id = ? AND emoji_key = ?
            """,
            (guild_id, message_id, emoji_key),
        ) as cursor:
            deleted = cursor.rowcount > 0
        await self.connection.commit()
        return deleted

    async def get_all_domme_profiles(self) -> list["DommeProfile"]:
        """Return all saved domme profiles, ordered by creation date."""
        async with self.connection.execute(
            "SELECT * FROM domme_profiles ORDER BY created_at ASC"
        ) as cursor:
            rows = await cursor.fetchall()
        return [DommeProfile.from_row(row) for row in rows]

    async def get_sub_leaderboard_rank(self, *, user_id: int) -> int | None:
        """Return the 1-based leaderboard rank for a sub, or None if they have no sends."""
        async with self.connection.execute(
            """
            SELECT rank FROM (
                SELECT
                    MAX(claimed_sub_user_id) AS claimed_sub_user_id,
                    SUM(amount_usd) AS total_usd,
                    COUNT(*) AS send_count,
                    ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC, SUM(amount_usd) DESC) AS rank
                FROM throne_sends
                GROUP BY
                    CASE
                        WHEN claimed_sub_user_id IS NOT NULL THEN 'claimed:' || CAST(claimed_sub_user_id AS TEXT)
                        WHEN sub_throne_name IS NOT NULL THEN 'name:' || sub_throne_name
                        ELSE 'anonymous'
                    END
            ) ranked
            WHERE claimed_sub_user_id = ?
            """,
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return int(row["rank"])

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
            SELECT
                user_id,
                throne_url,
                registered_at
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

    async def _fetch_one(
        self,
        query: str,
        params: tuple[Any, ...],
    ) -> VerificationRequest | None:
        async with self.connection.execute(query, params) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return VerificationRequest.from_row(row)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
