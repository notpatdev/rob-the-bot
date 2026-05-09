"""Throne webhook HTTP server for Rob the Bot.

Provides a POST endpoint that receives signed Throne gift events and inserts
them into the database, then fires Discord notifications.

Route: POST /throne/webhook/{creator_id}/{secret}
Health: GET /health
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from aiohttp import web

from bot.config import BotConfig
from bot.database import Database
from bot.utils import normalize_sender_name

if TYPE_CHECKING:
    import discord
    from discord.ext import commands

log = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_fallback_hash(
    creator_id: str,
    order_id: str | None,
    purchased_at: str | None,
    gifter_username: str | None,
    item_name: str | None,
    amount_cents: int | None,
    currency: str | None,
) -> str:
    parts = [
        creator_id,
        order_id or "",
        purchased_at or "",
        gifter_username or "",
        item_name or "",
        str(amount_cents) if amount_cents is not None else "",
        currency or "",
    ]
    raw = "|".join(parts).encode()
    return hashlib.sha256(raw).hexdigest()


def _extract_gift_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract normalised gift fields from a Throne webhook payload.
    
    Supports both the documented Throne webhook envelope where event-specific
    values live under ``payload["data"]`` and older / alternate top-level
    shapes. Never raises on missing fields.
    """
    
    def _as_dict(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}
    
    def _first(*values: Any) -> Any:
        for value in values:
            if value is not None:
                return value
        return None
    
    def _first_str(*values: Any) -> str | None:
        value = _first(*values)
        if value is None:
            return None
        text = str(value).strip()
        return text or None
    
    def _truthy(*values: Any) -> bool:
        for value in values:
            if bool(value):
                return True
        return False
    
    data = _as_dict(payload.get("data"))
    
    # Top-level envelope fields
    event_id: str | None = _first_str(
        payload.get("id"),
        payload.get("eventId"),
        payload.get("event_id"),
    )
    event_type: str | None = _first_str(
        payload.get("type"),
        payload.get("eventType"),
        payload.get("event_type"),
    )
    
    # Mixed top-level / nested fields
    order_id: str | None = _first_str(
        data.get("orderId"),
        data.get("order_id"),
        payload.get("orderId"),
        payload.get("order_id"),
    )
    status: str | None = _first_str(
        data.get("status"),
        payload.get("status"),
    )
    message: str | None = _first_str(
        data.get("message"),
        payload.get("message"),
    )
    
    purchased_at: str | None = _first_str(
        data.get("purchasedAt"),
        data.get("purchased_at"),
        data.get("createdAt"),
        data.get("created_at"),
        data.get("timestamp"),
        payload.get("purchasedAt"),
        payload.get("purchased_at"),
        payload.get("createdAt"),
        payload.get("created_at"),
        payload.get("timestamp"),
    )
    
    # Sender / gifter info
    gifter_obj: dict[str, Any] = {}
    for container in (data, payload):
        for key in ("gifter", "sender", "user"):
            value = container.get(key)
            if isinstance(value, dict):
                gifter_obj = value
                break
        if gifter_obj:
            break
    
    gifter_username: str | None = _first_str(
        gifter_obj.get("username"),
        gifter_obj.get("name"),
        data.get("gifterUsername"),
        data.get("gifter_username"),
        data.get("senderUsername"),
        data.get("sender_username"),
        data.get("senderName"),
        data.get("sender_name"),
        payload.get("gifterUsername"),
        payload.get("gifter_username"),
        payload.get("senderUsername"),
        payload.get("sender_username"),
        payload.get("senderName"),
        payload.get("sender_name"),
    )
    
    is_anonymous: bool = _truthy(
        gifter_obj.get("isAnonymous"),
        data.get("isAnonymous"),
        data.get("is_anonymous"),
        data.get("anonymous"),
        payload.get("isAnonymous"),
        payload.get("is_anonymous"),
        payload.get("anonymous"),
    )
    if is_anonymous:
        gifter_username = None
    
    # Item info
    item_obj: dict[str, Any] = {}
    for container in (data, payload):
        for key in ("gift", "item", "product", "wishlistItem"):
            value = container.get(key)
            if isinstance(value, dict):
                item_obj = value
                break
        if item_obj:
            break
    
    item_name: str | None = _first_str(
        item_obj.get("name"),
        item_obj.get("title"),
        data.get("itemName"),
        data.get("item_name"),
        payload.get("itemName"),
        payload.get("item_name"),
        payload.get("productName"),
        payload.get("product_name"),
        payload.get("giftName"),
        payload.get("gift_name"),
    )
    
    item_image_url: str | None = _first_str(
        item_obj.get("imageUrl"),
        item_obj.get("image_url"),
        item_obj.get("image"),
        data.get("itemThumbnailUrl"),
        data.get("item_thumbnail_url"),
        data.get("itemImageUrl"),
        data.get("item_image_url"),
        payload.get("itemThumbnailUrl"),
        payload.get("item_thumbnail_url"),
        payload.get("itemImageUrl"),
        payload.get("item_image_url"),
        payload.get("imageUrl"),
        payload.get("image_url"),
    )
    if item_image_url and not item_image_url.lower().startswith(("http://", "https://")):
        item_image_url = None
    
    currency: str | None = _first_str(
        data.get("currency"),
        payload.get("currency"),
        item_obj.get("currency"),
    )
    
    amount_cents: int | None = None
    amount_usd: float | None = None
    
    raw_cents = _first(
        data.get("amountCents"),
        data.get("amount_cents"),
        payload.get("amountCents"),
        payload.get("amount_cents"),
        payload.get("priceCents"),
        payload.get("price_cents"),
        item_obj.get("amountCents"),
        item_obj.get("amount_cents"),
    )
    
    if raw_cents is not None:
        try:
            amount_cents = int(raw_cents)
            amount_usd = amount_cents / 100.0
        except (TypeError, ValueError):
            pass
    
    if amount_usd is None:
        raw_amount = _first(
            data.get("amount"),
            payload.get("amount"),
            item_obj.get("amount"),
            data.get("amountUsd"),
            data.get("amount_usd"),
            data.get("priceUsd"),
            data.get("price_usd"),
            payload.get("amountUsd"),
            payload.get("amount_usd"),
            payload.get("priceUsd"),
            payload.get("price_usd"),
            item_obj.get("amountUsd"),
            item_obj.get("amount_usd"),
            item_obj.get("priceUsd"),
            item_obj.get("price_usd"),
        )
    
        if raw_amount is not None:
            try:
                if isinstance(raw_amount, str):
                    cleaned = raw_amount.strip().replace("$", "").replace(",", "")
                    if cleaned:
                        numeric_amount = float(cleaned)
                    else:
                        numeric_amount = None
                else:
                    numeric_amount = float(raw_amount)
    
                if numeric_amount is not None:
                    # Throne docs: contribution_purchased.data.amount is in minor units.
                    if (
                        event_type == "contribution_purchased"
                        and currency
                        and currency.upper() == "USD"
                    ):
                        amount_cents = int(round(numeric_amount))
                        amount_usd = amount_cents / 100.0
                    else:
                        amount_usd = numeric_amount
                        if amount_cents is None:
                            amount_cents = int(round(numeric_amount * 100))
            except (TypeError, ValueError):
                pass
    
    is_private: bool = _truthy(
        data.get("isPrivate"),
        data.get("is_private"),
        data.get("amountHidden"),
        data.get("hideAmount"),
        payload.get("isPrivate"),
        payload.get("is_private"),
        payload.get("amountHidden"),
        payload.get("hideAmount"),
    )
    if is_private:
        amount_usd = None
    
    return {
        "event_id": event_id,
        "event_type": event_type,
        "order_id": order_id,
        "status": status,
        "message": message,
        "purchased_at": purchased_at,
        "gifter_username": gifter_username,
        "is_anonymous": is_anonymous,
        "item_name": item_name,
        "item_image_url": item_image_url,
        "amount_cents": amount_cents,
        "amount_usd": amount_usd,
        "currency": currency,
        "is_private": is_private,
    }


def _verify_ed25519(
    public_key_pem: str,
    signature_hex: str,
    message: bytes,
) -> bool:
    """Verify an Ed25519 signature. Returns False on any error."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.hazmat.primitives.serialization import load_pem_public_key

        signature_bytes = bytes.fromhex(signature_hex)
        if len(signature_bytes) != 64:
            return False
        public_key = load_pem_public_key(public_key_pem.encode())
        if not isinstance(public_key, Ed25519PublicKey):
            log.warning("THRONE_PUBLIC_KEY_PEM is not an Ed25519 public key.")
            return False
        public_key.verify(signature_bytes, message)
        return True
    except Exception:
        return False


class ThroneWebhookServer:
    """Lifecycle-managed aiohttp server for Throne webhook events."""

    def __init__(
        self,
        bot: commands.Bot,
        config: BotConfig,
        database: Database,
    ) -> None:
        self.bot = bot
        self.config = config
        self.database = database
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

        if config.throne_webhook_require_signature and not config.throne_public_key_pem:
            log.error(
                "THRONE_PUBLIC_KEY_PEM is required when THRONE_WEBHOOK_REQUIRE_SIGNATURE=true. "
                "Webhook signature verification is enabled but no public key is set. "
                "All webhook requests will be rejected with 401."
            )
        if not config.throne_webhook_require_signature and not config.throne_public_key_pem:
            log.warning(
                "⚠️  THRONE_WEBHOOK_REQUIRE_SIGNATURE=false and THRONE_PUBLIC_KEY_PEM is unset. "
                "Webhook signature verification is DISABLED. This is insecure — for local testing only."
            )

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/health", self._handle_health)
        app.router.add_post("/throne/webhook/{creator_id}/{secret}", self._handle_webhook)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        self._site = web.TCPSite(
            self._runner,
            host="127.0.0.1",
            port=self.config.throne_webhook_port,
        )
        await self._site.start()
        log.info(
            "Throne webhook server listening on 127.0.0.1:%s",
            self.config.throne_webhook_port,
        )
        if self.config.throne_webhook_debug_log_payload:
            log.warning(
                "THRONE_WEBHOOK_DEBUG_LOG_PAYLOAD=true. Raw webhook bodies and parsed payload summaries "
                "will be written to logs and may include gift details or user data. Enable only temporarily."
            )

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            log.info("Throne webhook server stopped.")

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.Response(text="OK")

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        creator_id: str = request.match_info["creator_id"]
        url_secret: str = request.match_info["secret"]

        # 1. Read raw body bytes — must happen before any JSON parsing.
        raw_body: bytes = await request.read()
        config = self.config
        if config.throne_webhook_debug_log_payload:
            log.info(
                "Webhook debug payload for creator %s: %s",
                creator_id,
                raw_body.decode("utf-8", errors="replace"),
            )

        # 2 & 3. Timestamp verification.
        ts_header = request.headers.get(config.throne_webhook_timestamp_header, "")
        ts_stripped = ts_header.strip()
        if not ts_stripped.isdigit():
            log.debug("Webhook rejected: missing or non-numeric timestamp header.")
            return web.Response(status=401, text="Missing or invalid timestamp")
        ts_value = int(ts_stripped)
        now_ts = int(time.time())
        skew = abs(now_ts - ts_value)
        if skew > config.throne_webhook_max_timestamp_skew_seconds:
            log.debug("Webhook rejected: timestamp skew %ss exceeds limit.", skew)
            return web.Response(status=401, text="Timestamp out of range")

        # 4 & 5. Signature verification.
        sig_hex = request.headers.get(config.throne_webhook_signature_header, "").strip()

        if config.throne_webhook_require_signature:
            if not config.throne_public_key_pem:
                log.error("Webhook rejected: signature required but THRONE_PUBLIC_KEY_PEM not set.")
                return web.Response(status=401, text="Signature verification not configured")

            # Build the message to verify based on configured format.
            fmt = config.throne_webhook_signed_message_format
            if fmt == "timestamp_dot_body":
                message_to_verify = f"{ts_header}.".encode() + raw_body
            elif fmt == "timestamp_concat_body":
                message_to_verify = ts_header.encode() + raw_body
            else:
                # "body_only" or any unknown value — use raw body.
                message_to_verify = raw_body

            if not _verify_ed25519(config.throne_public_key_pem, sig_hex, message_to_verify):
                log.warning("Webhook rejected: Ed25519 signature verification failed for creator %s.", creator_id)
                return web.Response(status=401, text="Invalid signature")

        # 6. Look up throne_creators row by creator_id.
        rows = await self.database.get_throne_creators_by_creator_id(
            throne_creator_id=creator_id
        )
        if not rows:
            log.debug("Webhook: no throne_creators row for creator_id=%s", creator_id)
            return web.Response(status=404, text="Creator not found")

        # 7. Find the row whose webhook_secret matches the URL secret.
        matched_row = None
        for row in rows:
            if hmac.compare_digest(url_secret, row.webhook_secret):
                matched_row = row
                break
        if matched_row is None:
            log.warning("Webhook: secret mismatch for creator_id=%s", creator_id)
            return web.Response(status=403, text="Forbidden")

        # 8. Parse JSON payload.
        try:
            payload: dict[str, Any] = json.loads(raw_body.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            log.warning("Webhook: bad JSON from creator %s: %s", creator_id, exc)
            return web.Response(status=400, text="Invalid JSON")

        # 9. Extract gift fields.
        fields = _extract_gift_fields(payload)
        if config.throne_webhook_debug_log_payload:
            log.info(
                "Webhook debug summary for creator %s: event_id=%r event_type=%r data=%s fields=%s",
                creator_id,
                fields["event_id"],
                fields["event_type"],
                payload.get("data"),
                fields,
            )

        event_type = fields["event_type"] or ""
        # Only process purchase events; ignore pings / test events gracefully.
        accepted_types = {
            "gift_purchased",
            "contribution_purchased",
            "gift_crowdfunded",
            "item_purchased",
        }
        if event_type and event_type not in accepted_types:
            log.debug("Webhook: ignoring event_type=%r for creator %s", event_type, creator_id)
            return web.json_response({"ok": True, "ignored": True, "event_type": event_type})

        event_id: str | None = fields["event_id"]

        # 10. Compute fallback hash if event_id is missing.
        fallback_event_hash: str | None = None
        if not event_id:
            fallback_event_hash = _compute_fallback_hash(
                creator_id=creator_id,
                order_id=fields["order_id"],
                purchased_at=fields["purchased_at"],
                gifter_username=fields["gifter_username"],
                item_name=fields["item_name"],
                amount_cents=fields["amount_cents"],
                currency=fields["currency"],
            )

        domme_user_id = int(matched_row.discord_user_id)
        amount_usd = fields["amount_usd"] if fields["amount_usd"] is not None else 0.0
        is_private = fields["is_private"]

        # Determine active event key.
        event_cog = self.bot.get_cog("RobEventCog")
        event_key: str | None = None
        if event_cog is not None:
            ctx = await event_cog.get_runtime_context()
            if ctx is not None and ctx.is_event_active:
                event_key = ctx.event_key

        # 11. Insert into event_sends — dedup via unique indexes.
        send_id = await self.database.log_event_send(
            domme_user_id=domme_user_id,
            sub_name=normalize_sender_name(fields["gifter_username"]),
            amount_usd=amount_usd,
            item_name=fields["item_name"],
            item_image_url=fields["item_image_url"],
            logged_by=self.bot.user.id if self.bot.user else 0,
            external_id=None,
            event_id=event_id or None,
            fallback_event_hash=fallback_event_hash,
            source="webhook",
            is_private=is_private,
            seeded=False,
            sent_at=fields["purchased_at"],
            event_key=event_key,
        )

        if send_id is None:
            # Duplicate.
            return web.json_response({"ok": True, "duplicate": True})

        # 12. Update throne_creators tracking state.
        now_str = _utc_now()
        await self.database.update_throne_creator_webhook_connected(
            creator_id=matched_row.id,
            webhook_connected_at=now_str,
            last_successful_event_at=now_str,
        )

        # 13. Schedule Discord notification without blocking the response.
        import asyncio
        asyncio.create_task(self._post_send_notification(domme_user_id, send_id))

        # 14. Return success.
        return web.json_response({"ok": True, "inserted": True})

    async def _post_send_notification(self, domme_user_id: int, send_id: int) -> None:
        """Post send card and sync leaderboard. Runs in a task, never raises."""
        try:
            tracker_cog = self.bot.get_cog("ThroneTrackerCog")
            if tracker_cog is not None:
                await tracker_cog._post_send_card(domme_user_id, send_id)

            event_cog = self.bot.get_cog("RobEventCog")
            if event_cog is not None:
                await event_cog.sync_leaderboard_channel()
        except Exception:
            log.exception("Failed to post webhook send notification for send_id=%s", send_id)
