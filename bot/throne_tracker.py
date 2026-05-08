"""Background Throne tracker for Rob the Bot."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import secrets
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

import aiohttp
import discord
from discord.ext import commands, tasks

from bot.config import BotConfig
from bot.database import Database, EventDommeRegistration
from bot.event_views import SendNotificationView, ThroneRefreshView, format_money, format_timestamp
from bot.ui.components import action_section, make_container, separator, simple_view, text_block
from bot.throne_scraper import fetch_recent_sends_with_status, normalize_throne_url
from bot.utils import has_admin_command_permissions

log = logging.getLogger(__name__)

_FAILURE_THRESHOLD = 5
_SLOW_RETRY_INTERVAL_S = 60 * 60
_PAGE_ENRICHMENT_COOLDOWN_S = 60 * 60
_DISCORD_USER_REF_RE = re.compile(r"^<@!?(\d+)>$")
_EMBED_COLOR_SUCCESS = 5_763_719
_EMBED_COLOR_ERROR = 13_595_942
_EMBED_COLOR_ADMIN = 15_379_208
_DEFAULT_WEBHOOK_BASE_URL = "https://rob.barecoding.com"


@dataclass(frozen=True)
class PollCycleResult:
    ran: bool
    new_sends_found: int


class ThroneWebhookRefreshConfirmView(discord.ui.LayoutView):
    def __init__(
        self,
        *,
        cog: "ThroneTrackerCog",
        requester_id: int,
        creator_id: int,
        discord_user_id: int,
        throne_handle: str,
        throne_creator_id: str,
    ) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.requester_id = requester_id
        self.creator_id = creator_id
        self.discord_user_id = discord_user_id
        self.throne_handle = throne_handle
        self.throne_creator_id = throne_creator_id

        yes_button = discord.ui.Button(label="Yes", style=discord.ButtonStyle.primary)
        no_button = discord.ui.Button(label="No", style=discord.ButtonStyle.secondary)
        yes_button.callback = self._confirm
        no_button.callback = self._cancel

        self.add_item(
            make_container(
                "👑 Rob | Throne Admin | Webhook",
                "Webhook Refresh Request!",
                sections=[
                    separator(),
                    text_block(f"**Throne UID**\n`{self.throne_creator_id}`"),
                    text_block(f"**Throne Username**\n{self.throne_handle}"),
                    text_block(f"**Discord User**\n<@{self.discord_user_id}>"),
                    separator(),
                    text_block(
                        "Do you wish to proceed? This will rotate the webhook secret and DM the user "
                        "a new URL. Their old URL will stop working immediately."
                    ),
                    separator(),
                    action_section("Proceed with webhook reset.", yes_button),
                    action_section("Cancel this request.", no_button),
                ],
                accent_color=_EMBED_COLOR_ADMIN,
                footer="Rob can still walk this back by doing nothing.",
            )
        )

    async def _ensure_requester(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return True
        await interaction.response.send_message("That button is not for you.", ephemeral=True)
        return False

    async def _confirm(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_requester(interaction):
            return

        webhook_secret = secrets.token_urlsafe(32)
        await self.cog.database.reset_throne_creator_webhook(
            creator_id=self.creator_id,
            webhook_secret=webhook_secret,
        )

        webhook_url = self.cog._build_webhook_url(self.throne_creator_id, webhook_secret)
        dm_failed = False
        try:
            user = self.cog.bot.get_user(self.discord_user_id) or await self.cog.bot.fetch_user(self.discord_user_id)
            await user.send(
                view=simple_view(
                    "👑 Rob | Throne | Webhook Reset",
                    (
                        f"New webhook URL:\n`{webhook_url}`\n\n"
                        "Go to Throne → Settings → Integrations → Webhooks. Replace the old URL with this one. "
                        "Click Save Settings. Then click Test Webhook.\n\n"
                        "The old URL no longer works."
                    ),
                    accent_color=_EMBED_COLOR_ADMIN,
                    footer="Rob rotated the key. Please paste carefully.",
                    timeout=600,
                )
            )
        except (discord.Forbidden, discord.HTTPException):
            dm_failed = True

        await interaction.response.edit_message(
            view=simple_view(
                "✅ Rob | Success | Throne Webhook",
                (
                    f"✅ Webhook secret rotated for `{self.throne_handle}` and DM sent."
                    if not dm_failed
                    else f"✅ Webhook secret rotated for `{self.throne_handle}`."
                ),
                accent_color=_EMBED_COLOR_SUCCESS,
                footer="Rob changed the lock and mailed the key.",
                timeout=60,
            )
        )
        if dm_failed:
            await interaction.followup.send(
                (
                    "Could not DM user — here's the URL, send it manually:\n"
                    f"`{webhook_url}`"
                ),
                ephemeral=True,
            )

    async def _cancel(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_requester(interaction):
            return
        await interaction.response.edit_message(
            view=simple_view(
                "👑 Rob | Throne Admin | Webhook",
                "Cancelled.",
                accent_color=_EMBED_COLOR_ADMIN,
                footer="Rob closed the ticket. No changes made.",
                timeout=30,
            )
        )


class ThroneTrackerCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        config: BotConfig,
        database: Database,
    ) -> None:
        self.bot = bot
        self.config = config
        self.database = database
        self._http: aiohttp.ClientSession | None = None
        self._failure_counts: dict[int, int] = {}
        self._slow_retry_until: dict[int, float] = {}
        self._page_enrichment_cooldown_until: dict[int, float] = {}
        self._poll_lock = asyncio.Lock()
        self._warned_runtime_targets: set[str] = set()
        self._last_poll_at: str | None = None
        self._last_successful_poll_at: str | None = None
        self._last_manual_refresh_at: str | None = None
        self._last_error: str | None = None

        self.poll_throne_pages.change_interval(seconds=config.throne_poll_interval_seconds)
        self.poll_throne_pages.start()

    def cog_unload(self) -> None:
        self.poll_throne_pages.cancel()
        if self._http is not None:
            session = self._http
            self._http = None
            asyncio.create_task(session.close())

    async def _get_http(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession()
        return self._http

    def _warn_once(self, key: str, message: str, *args: object) -> None:
        if key in self._warned_runtime_targets:
            return
        self._warned_runtime_targets.add(key)
        log.warning(message, *args)

    @tasks.loop(seconds=300)
    async def poll_throne_pages(self) -> None:
        try:
            await self._run_poll_cycle()
        except Exception:  # noqa: BLE001 - keep the loop alive
            self._last_error = "Polling cycle crashed before completion."
            log.exception("Throne polling cycle raised; will retry next interval.")

    @poll_throne_pages.before_loop
    async def _before_poll(self) -> None:
        await self.bot.wait_until_ready()

    @commands.group(name="throne", invoke_without_command=True)
    async def throne_group(self, ctx: commands.Context[commands.Bot]) -> None:
        await ctx.reply(
            "Rob knows: `!throne refresh` `!throne status` `!throne list` `!throne search <@user|id>` "
            "`!throne webhook refresh <@user|id>`",
            mention_author=False,
        )

    @throne_group.command(name="refresh")
    async def throne_refresh(self, ctx: commands.Context[commands.Bot]) -> None:
        if not await self._check_admin_context(ctx):
            return

        result = await self.run_manual_refresh()
        event_cog = self.bot.get_cog("RobEventCog")
        context = await event_cog.get_runtime_context() if event_cog is not None else None
        tracking_mode = self._refresh_mode_label(context)
        detail = (
            "Manual refresh complete."
            if result.ran
            else "A poll is already running. Rob is not doing two at once."
        )
        await ctx.reply(
            view=ThroneRefreshView(
                ran=result.ran,
                detail=detail,
                new_sends_found=result.new_sends_found,
                tracking_mode=tracking_mode,
                slow_retry_count=self.slow_retry_count(),
                page_cooldown_count=self.page_enrichment_cooldown_count(),
            ),
            mention_author=False,
        )

    @throne_group.command(name="status")
    async def throne_status(self, ctx: commands.Context[commands.Bot]) -> None:
        if not await self._check_admin_context(ctx):
            return

        if ctx.guild is None:
            await ctx.reply("Server only.", mention_author=False)
            return

        creators = await self.database.get_throne_creators_for_guild(guild_id=str(ctx.guild.id))
        total_count = len(creators)
        webhook_count = sum(1 for creator in creators if creator.tracking_mode == "webhook")
        inactive_count = total_count - webhook_count
        tracking_method = "Legacy"
        if webhook_count and inactive_count:
            tracking_method = "Mixed (webhook + legacy)"
        elif webhook_count:
            tracking_method = "Webhook"

        latest = await self.database.get_latest_webhook_send_for_guild(guild_id=str(ctx.guild.id))
        if latest is None:
            last_send_line = "Never"
            last_send_user_line = "Unknown"
        else:
            user_label = await self._member_display_label(ctx.guild, int(latest.discord_user_id))
            last_send_line = format_timestamp(latest.sent_at)
            last_send_user_line = user_label

        await ctx.reply(
            view=self._simple_admin_view(
                "👑 Rob | Throne Admin | Status",
                sections=[
                    text_block(f"**Current Tracking Method**\n{tracking_method}"),
                    separator(),
                    text_block(f"**Registered Users**\n{total_count}"),
                    separator(),
                    text_block(f"**Webhook Active**\n{webhook_count}"),
                    separator(),
                    text_block(f"**Disabled / Inactive Webhook**\n{inactive_count}"),
                    separator(),
                    text_block(
                        "**Last Successful Send Notification**\n"
                        f"Time: {last_send_line}\n"
                        f"User: {last_send_user_line}"
                    ),
                ],
                footer="Rob keeps the books. The books keep Rob employed.",
                accent_color=_EMBED_COLOR_ADMIN,
            ),
            mention_author=False,
        )

    @throne_group.command(name="list")
    async def throne_list(self, ctx: commands.Context[commands.Bot]) -> None:
        if not await self._check_admin_context(ctx):
            return
        if ctx.guild is None:
            await ctx.reply("Server only.", mention_author=False)
            return

        creators = await self.database.get_throne_creators_for_guild(guild_id=str(ctx.guild.id))
        total_count = len(creators)
        if not creators:
            await ctx.reply(
                view=self._simple_admin_view(
                    "👑 Rob | Throne Admin | Users",
                    sections=[text_block("No creators are registered yet.")],
                    footer="Total registered: 0",
                    accent_color=_EMBED_COLOR_ADMIN,
                ),
                mention_author=False,
            )
            return

        pages = self._chunked(creators, 8)
        for index, page in enumerate(pages):
            sections: list[discord.ui.Item] = []
            for creator_index, creator in enumerate(page):
                user_label = await self._member_display_label(ctx.guild, int(creator.discord_user_id))
                status = "🟢 Active" if creator.tracking_mode == "webhook" else "⚪ Disabled"
                if creator.last_successful_event_at:
                    status = f"{status} · last event {format_timestamp(creator.last_successful_event_at).split(' / ')[0]}"
                if creator_index:
                    sections.append(separator())
                sections.append(
                    text_block(
                        f"**Nickname:** **{user_label}**\n"
                        f"Throne Username: `{creator.throne_handle}`\n"
                        f"Throne UID: `{creator.throne_creator_id}`\n"
                        f"Webhook Status: {status}"
                    )
                )
            footer = f"Total registered: {total_count}"
            if len(pages) > 1:
                footer = f"{footer} · Page {index + 1}/{len(pages)}"
            view = self._simple_admin_view(
                "👑 Rob | Throne Admin | Users",
                sections=sections,
                footer=footer,
                accent_color=_EMBED_COLOR_ADMIN,
            )
            if index == 0:
                await ctx.reply(view=view, mention_author=False)
            else:
                await ctx.send(view=view)

    @throne_group.command(name="search")
    async def throne_search(self, ctx: commands.Context[commands.Bot], user_ref: str) -> None:
        if not await self._check_admin_context(ctx):
            return
        if ctx.guild is None:
            await ctx.reply("Server only.", mention_author=False)
            return

        user_id = self._parse_user_id(user_ref)
        if user_id is None:
            await ctx.reply(
                view=self._simple_admin_view(
                    "⚠️ Rob | Errors | Throne Search",
                    sections=[text_block("No Throne registration found for that user.")],
                    footer="Rob checked. Nothing filed under that reference.",
                    accent_color=_EMBED_COLOR_ERROR,
                ),
                mention_author=False,
            )
            return

        creator = await self.database.get_throne_creator_by_discord_user(
            guild_id=str(ctx.guild.id),
            discord_user_id=str(user_id),
        )
        if creator is None:
            await ctx.reply(
                view=self._simple_admin_view(
                    "⚠️ Rob | Errors | Throne Search",
                    sections=[text_block("No Throne registration found for that user.")],
                    footer="Rob checked. Nothing filed under that reference.",
                    accent_color=_EMBED_COLOR_ERROR,
                ),
                mention_author=False,
            )
            return

        latest_send = await self.database.get_latest_webhook_send_for_domme(domme_user_id=user_id)
        if latest_send is None:
            send_time = "Never"
            send_from = "Unknown"
            send_amount = "Unknown"
        else:
            send_time = format_timestamp(latest_send.sent_at)
            send_from = latest_send.sub_name or "Unknown"
            send_amount = "Unknown" if latest_send.is_private else format_money(latest_send.amount_usd)

        webhook_status = "🟢 Active" if creator.tracking_mode == "webhook" else "⚪ Disabled"
        connected_at = format_timestamp(creator.webhook_connected_at) if creator.webhook_connected_at else "Never"
        user_label = await self._member_display_label(ctx.guild, user_id)
        await ctx.reply(
            view=self._simple_admin_view(
                "👑 Rob | Throne Admin | Details",
                sections=[
                    text_block(
                        "**Identity**\n"
                        f"Discord: {user_label}\n"
                        f"Throne Username: `{creator.throne_handle}`\n"
                        f"Throne UID: `{creator.throne_creator_id}`"
                    ),
                    separator(),
                    text_block(
                        "**Last Recorded Send**\n"
                        f"Time: {send_time}\n"
                        f"From: {send_from}\n"
                        f"Amount: {send_amount}"
                    ),
                    separator(),
                    text_block(
                        "**Webhook Status**\n"
                        f"{webhook_status}\n"
                        f"Connected at: {connected_at}"
                    ),
                ],
                footer="Rob found the row. Begrudgingly.",
                accent_color=_EMBED_COLOR_ADMIN,
            ),
            mention_author=False,
        )

    @throne_group.group(name="webhook", invoke_without_command=True)
    async def throne_webhook_group(self, ctx: commands.Context[commands.Bot]) -> None:
        await ctx.reply("Rob knows: `!throne webhook refresh <@user|id>`", mention_author=False)

    @throne_webhook_group.command(name="refresh")
    async def throne_webhook_refresh(self, ctx: commands.Context[commands.Bot], user_ref: str) -> None:
        if not await self._check_admin_context(ctx):
            return
        if ctx.guild is None:
            await ctx.reply("Server only.", mention_author=False)
            return
        if not await self._check_owner_context(ctx):
            await ctx.reply("Not authorized.", mention_author=False)
            return

        user_id = self._parse_user_id(user_ref)
        if user_id is None:
            await ctx.reply(
                view=self._simple_admin_view(
                    "⚠️ Rob | Errors | Throne Webhook",
                    sections=[text_block("No Throne registration found for that user.")],
                    footer="Rob cannot rotate a key without a matching row.",
                    accent_color=_EMBED_COLOR_ERROR,
                ),
                mention_author=False,
            )
            return

        creator = await self.database.get_throne_creator_by_discord_user(
            guild_id=str(ctx.guild.id),
            discord_user_id=str(user_id),
        )
        if creator is None:
            await ctx.reply(
                view=self._simple_admin_view(
                    "⚠️ Rob | Errors | Throne Webhook",
                    sections=[text_block("No Throne registration found for that user.")],
                    footer="Rob cannot rotate a key without a matching row.",
                    accent_color=_EMBED_COLOR_ERROR,
                ),
                mention_author=False,
            )
            return

        await ctx.reply(
            view=ThroneWebhookRefreshConfirmView(
                cog=self,
                requester_id=ctx.author.id,
                creator_id=creator.id,
                discord_user_id=int(creator.discord_user_id),
                throne_handle=creator.throne_handle,
                throne_creator_id=creator.throne_creator_id,
            ),
            mention_author=False,
        )

    async def _check_admin_context(self, ctx: commands.Context[commands.Bot]) -> bool:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.reply("Server only.", mention_author=False)
            return False
        if not has_admin_command_permissions(ctx.author, self.config):
            await ctx.reply("Nope. Not for you.", mention_author=False)
            return False
        return True

    async def _check_owner_context(self, ctx: commands.Context[commands.Bot]) -> bool:
        owner_ids: set[int] = set()
        raw_owner_ids = os.getenv("BOT_OWNER_ID", "").strip()
        if raw_owner_ids:
            for raw in raw_owner_ids.split(","):
                raw = raw.strip()
                if raw.isdigit():
                    owner_ids.add(int(raw))
        try:
            app_info = await self.bot.application_info()
            if app_info.owner is not None:
                owner_ids.add(app_info.owner.id)
        except discord.HTTPException:
            log.warning("Could not resolve bot application owner for webhook refresh checks.", exc_info=True)
        return ctx.author.id in owner_ids

    @staticmethod
    def _parse_user_id(raw: str) -> int | None:
        cleaned = raw.strip()
        if cleaned.isdigit():
            return int(cleaned)
        match = _DISCORD_USER_REF_RE.match(cleaned)
        if match:
            return int(match.group(1))
        return None

    async def _member_display_label(self, guild: discord.Guild, user_id: int) -> str:
        member = guild.get_member(user_id)
        if member is not None:
            return f"<@{user_id}> ({member.display_name})"
        return f"<@{user_id}>"

    def _simple_admin_view(
        self,
        title: str,
        *,
        sections: list[discord.ui.Item],
        footer: str,
        accent_color: int,
    ) -> discord.ui.LayoutView:
        view = discord.ui.LayoutView(timeout=120)
        view.add_item(
            make_container(
                title,
                sections=sections,
                footer=footer,
                accent_color=accent_color,
            )
        )
        return view

    @staticmethod
    def _chunked(items: Sequence[object], size: int) -> list[list[object]]:
        return [list(items[index:index + size]) for index in range(0, len(items), size)]

    def _build_webhook_url(self, creator_id: str, secret: str) -> str:
        base_url = (self.config.throne_webhook_base_url or _DEFAULT_WEBHOOK_BASE_URL).rstrip("/")
        return f"{base_url}/throne/webhook/{creator_id}/{secret}"

    async def run_manual_refresh(self) -> PollCycleResult:
        if self._poll_lock.locked():
            return PollCycleResult(ran=False, new_sends_found=0)
        new_sends = await self._run_poll_cycle()
        self._last_manual_refresh_at = datetime.now(timezone.utc).isoformat()
        return PollCycleResult(ran=True, new_sends_found=new_sends)

    async def _run_poll_cycle(self, *, force_domme_user_id: int | None = None) -> int:
        async with self._poll_lock:
            self._last_poll_at = datetime.now(timezone.utc).isoformat()
            cycle_error: str | None = None

            event_cog = self.bot.get_cog("RobEventCog")
            context = await event_cog.get_runtime_context() if event_cog is not None else None
            active_event_key = context.event_key if context is not None and context.is_event_active else None

            profiles = await self.database.get_all_event_dommes()
            tracked = [
                profile
                for profile in profiles
                if profile.throne_url and normalize_throne_url(profile.throne_url) is not None
            ]
            if force_domme_user_id is not None:
                tracked = [profile for profile in tracked if profile.user_id == force_domme_user_id]

            if not tracked:
                self._last_successful_poll_at = datetime.now(timezone.utc).isoformat()
                self._last_error = None
                return 0

            if force_domme_user_id is None:
                random.shuffle(tracked)

            posted_total = 0
            for index, profile in enumerate(tracked):
                if force_domme_user_id is None and self._is_in_slow_retry(profile.user_id):
                    continue
                try:
                    posted_total += await self._poll_one_domme(profile, event_key=active_event_key)
                except Exception as exc:  # noqa: BLE001
                    cycle_error = f"Domme {profile.user_id} poll failed: {exc}"
                    log.exception("Unexpected error polling Domme %s; continuing.", profile.user_id)
                if index < len(tracked) - 1:
                    delay = self.config.throne_poll_per_domme_delay_seconds
                    if delay > 0:
                        await asyncio.sleep(delay + random.uniform(0, delay / 2))

            if posted_total > 0 and event_cog is not None:
                try:
                    await event_cog.sync_leaderboard_channel(context=context)
                except Exception:  # noqa: BLE001
                    cycle_error = "Leaderboard sync failed after polling."
                    log.exception("Failed to sync leaderboard channel after Throne poll.")

            self._last_successful_poll_at = datetime.now(timezone.utc).isoformat()
            self._last_error = cycle_error
            return posted_total

    def _is_in_slow_retry(self, domme_user_id: int) -> bool:
        until = self._slow_retry_until.get(domme_user_id)
        if until is None:
            return False
        if time.monotonic() >= until:
            self._slow_retry_until.pop(domme_user_id, None)
            return False
        return True

    def _is_page_enrichment_on_cooldown(self, domme_user_id: int) -> bool:
        until = self._page_enrichment_cooldown_until.get(domme_user_id)
        if until is None:
            return False
        if time.monotonic() >= until:
            self._page_enrichment_cooldown_until.pop(domme_user_id, None)
            return False
        return True

    def _record_failure(self, domme_user_id: int) -> None:
        count = self._failure_counts.get(domme_user_id, 0) + 1
        self._failure_counts[domme_user_id] = count
        if count == _FAILURE_THRESHOLD:
            self._slow_retry_until[domme_user_id] = time.monotonic() + _SLOW_RETRY_INTERVAL_S
            log.warning(
                "Throne scraping for Domme %s failed %s times in a row; backing off to 1-hour retry.",
                domme_user_id,
                count,
            )

    def _record_success(self, domme_user_id: int) -> None:
        self._failure_counts.pop(domme_user_id, None)
        self._slow_retry_until.pop(domme_user_id, None)

    def _start_page_enrichment_cooldown(self, domme_user_id: int) -> None:
        if self._is_page_enrichment_on_cooldown(domme_user_id):
            return
        self._page_enrichment_cooldown_until[domme_user_id] = time.monotonic() + _PAGE_ENRICHMENT_COOLDOWN_S
        log.warning(
            "Throne page enrichment for Domme %s hit HTTP 429. Pausing page enrichment for 60 minutes while overlay tracking keeps running.",
            domme_user_id,
        )

    async def _poll_one_domme(self, profile: EventDommeRegistration, *, event_key: str | None) -> int:
        assert profile.throne_url is not None
        http = await self._get_http()
        result = await fetch_recent_sends_with_status(
            profile.throne_url,
            http=http,
            user_agent=self.config.throne_user_agent,
            timeout_seconds=self.config.throne_http_timeout_seconds,
            allow_page_enrichment=not self._is_page_enrichment_on_cooldown(profile.user_id),
        )

        if result.page_status == "rate_limited":
            self._start_page_enrichment_cooldown(profile.user_id)

        if result.sends is None:
            self._record_failure(profile.user_id)
            return 0

        self._record_success(profile.user_id)
        scraped = result.sends
        if not scraped:
            return 0

        is_first_run = not await self.database.has_any_event_sends_for_domme(domme_user_id=profile.user_id)
        known_external_ids = await self.database.get_known_event_external_ids_for_domme(domme_user_id=profile.user_id)
        new_items = [item for item in scraped if item.external_id not in known_external_ids]
        if not new_items:
            return 0

        posted = 0
        for item in new_items:
            send_id = await self.database.log_event_send(
                domme_user_id=profile.user_id,
                sub_name=item.sender_name,
                amount_usd=item.amount_usd if item.amount_usd is not None else 0.0,
                item_name=item.item_name,
                item_image_url=item.item_image_url,
                logged_by=self.bot.user.id if self.bot.user else 0,
                external_id=item.external_id,
                is_private=item.amount_usd is None,
                seeded=is_first_run,
                sent_at=item.sent_at,
                event_key=event_key,
            )
            if send_id is None or is_first_run:
                continue
            await self._post_send_card(profile.user_id, send_id)
            posted += 1
        return posted

    async def _post_send_card(self, domme_user_id: int, send_id: int) -> None:
        if not self.config.send_track_channel_id:
            return
        guild = self.bot.get_guild(self.config.guild_id)
        if guild is None:
            return
        channel = guild.get_channel(self.config.send_track_channel_id)
        if not isinstance(channel, discord.TextChannel):
            self._warn_once(
                "send_track_channel_runtime",
                "Send-track channel %s is not a text channel; cannot post send cards.",
                self.config.send_track_channel_id,
            )
            return

        send = await self.database.get_event_send(send_id=send_id)
        if send is None:
            return

        domme: discord.Member | discord.User | None = guild.get_member(domme_user_id)
        if domme is None:
            try:
                domme = await self.bot.fetch_user(domme_user_id)
            except (discord.NotFound, discord.HTTPException):
                domme = None

        sub_member: discord.Member | discord.User | None = None
        if send.claimed_sub_user_id is not None:
            sub_member = guild.get_member(send.claimed_sub_user_id)
            if sub_member is None:
                try:
                    sub_member = await self.bot.fetch_user(send.claimed_sub_user_id)
                except (discord.NotFound, discord.HTTPException):
                    sub_member = None

        event_cog = self.bot.get_cog("RobEventCog")
        theme = event_cog.events_config.default_theme if event_cog is not None else None
        if event_cog is not None and send.event_key:
            configured_event = event_cog.events_config.get_event(send.event_key)
            if configured_event is not None:
                theme = configured_event.theme
        elif event_cog is not None:
            theme = event_cog.events_config.default_theme

        sub_rank = (
            await self.database.get_event_sub_rank(
                user_id=send.claimed_sub_user_id,
                event_key=send.event_key,
            )
            if send.claimed_sub_user_id is not None
            else None
        )
        domme_totals = await self.database.get_event_domme_total(
            user_id=domme_user_id,
            event_key=send.event_key,
        )

        sub_label = sub_member.mention if sub_member is not None else (send.sub_name or "Unclaimed Send")
        domme_label = domme.mention if domme is not None else f"<@{domme_user_id}>"
        amount_label = format_money(send.amount_usd) if not send.is_private else "Unknown"
        title = "🎉 Rob | Events | Send"
        accent_color = theme.accent_color if theme is not None else discord.Colour.green()
        rank_label = "Event sub rank" if send.event_key else "Live sub rank"

        try:
            await channel.send(
                view=SendNotificationView(
                    title=title,
                    accent_color=accent_color,
                    sub_label=sub_label,
                    domme_label=domme_label,
                    amount_label=amount_label,
                    item_name=send.item_name,
                    item_image_url=send.item_image_url,
                    sub_rank=sub_rank,
                    domme_send_count=domme_totals.send_count,
                    rank_label=rank_label,
                )
            )
        except discord.HTTPException:
            self._last_error = f"Failed to post send notification for send id {send_id}."
            log.exception(
                "Failed to post send notification for send id %s in channel %s.",
                send_id,
                self.config.send_track_channel_id,
            )

    def slow_retry_count(self) -> int:
        active = [domme_id for domme_id in list(self._slow_retry_until) if self._is_in_slow_retry(domme_id)]
        return len(active)

    def page_enrichment_cooldown_count(self) -> int:
        active = [
            domme_id
            for domme_id in list(self._page_enrichment_cooldown_until)
            if self._is_page_enrichment_on_cooldown(domme_id)
        ]
        return len(active)

    def _format_iso_label(self, value: str | None) -> str:
        return format_timestamp(value)

    @staticmethod
    def _refresh_mode_label(context: object | None) -> str:
        if context is not None and getattr(context, "is_event_active", False):
            active_event = getattr(context, "active_event", None)
            if active_event is not None:
                return f"{active_event.name} — active"
        return "Live"

    @staticmethod
    def _current_event_label(context: object | None) -> str:
        if context is not None and getattr(context, "is_event_active", False):
            active_event = getattr(context, "active_event", None)
            if active_event is not None:
                return f"{active_event.name} — active"
        return "Not active. Live mode."
