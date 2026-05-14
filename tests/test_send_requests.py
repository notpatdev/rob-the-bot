from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.database import Database


class TestSendRequests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self._tmp.name) / "test.sqlite3")
        await self.database.initialize()

    async def asyncTearDown(self) -> None:
        await self.database.close()
        self._tmp.cleanup()

    async def test_count_send_requests_since_filters_by_window(self) -> None:
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=25)).isoformat()
        recent = (now - timedelta(hours=2)).isoformat()
        since = (now - timedelta(hours=24)).isoformat()

        await self.database.create_send_request(
            sub_user_id=101,
            domme_user_id=202,
            amount_usd=10.0,
            method="cashapp",
            note=None,
            created_at=old,
        )
        for _ in range(3):
            await self.database.create_send_request(
                sub_user_id=101,
                domme_user_id=202,
                amount_usd=10.0,
                method="cashapp",
                note=None,
                created_at=recent,
            )

        count = await self.database.count_send_requests_since(
            sub_user_id=101,
            domme_user_id=202,
            since=since,
        )
        self.assertEqual(count, 3)

    async def test_resolve_send_request_updates_status(self) -> None:
        request_id = await self.database.create_send_request(
            sub_user_id=333,
            domme_user_id=444,
            amount_usd=42.0,
            method="paypal",
            note="proof",
        )

        await self.database.resolve_send_request(request_id=request_id, status="approved")
        row = await self.database.get_send_request(request_id=request_id)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.status, "approved")
        self.assertIsNotNone(row.resolved_at)
