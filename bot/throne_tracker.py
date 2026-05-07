"""Background task that polls registered Dommes' Throne alerts and posts new sends.

The polling loop runs every ``THRONE_POLL_INTERVAL_SECONDS``. For each event
Domme with a registered Throne URL, we first query the public browser-source
alert overlays, then optionally enrich missing amounts from the public Throne
page when available. New sends are diffed against SQLite by ``external_id``,
inserted into the event send table, and posted to the configured send-track
channel.

The very first poll for a given Domme **seeds** the database with the current
page contents but does not post notification cards — this prevents a flood of historic
sends the first time a Domme opts in.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import discord
import aiohttp
from discord.ext import commands, tasks

from bot.config import BotConfig
from bot.database import Database, EventDommeRegistration
from bot.event_embeds import format_money
from bot.event_views import SendNotificationView
from bot.throne_scraper import ScrapedSend, fetch_recent_sends, normalize_throne_url

log = logging.getLogger(__name__)

# A Domme is moved to the slow-retry bucket after this many consecutive
# scrape failures, and re-tried at most once per ``_SLOW_RETRY_INTERVAL_S``.
_FAILURE_THRESHOLD = 5
_SLOW_RETRY_INTERVAL_S = 60 * 60  # 1 hour


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
        # domme_user_id -> consecutive failure count
        self._failure_counts: dict[int, int] = {}
        # domme_user_id -> monotonic time when slow-retry cooldown expires
        self._slow_retry_until: dict[int, float] = {}
        self._poll_lock = asyncio.Lock()

        # Configure the loop interval from config at decoration time.
        self.poll_throne_pages.change_interval(
            seconds=config.throne_poll_interval_seconds
        )
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

    # The decorator requires a literal interval; the real value is applied
    # via change_interval() in __init__ from BotConfig.
    @tasks.loop(seconds=300)
    async def poll_throne_pages(self) -> None:
        try:
            await self._run_poll_cycle()
        except Exception:  # noqa: BLE001 - keep the loop alive
            log.exception("Throne polling cycle raised; will retry next interval.")

    @poll_throne_pages.before_loop
    async def _before_poll(self) -> None:
        await self.bot.wait_until_ready()

    async def _run_poll_cycle(self, *, force_domme_user_id: int | None = None) -> int:
        """Run one polling cycle. Returns number of new sends posted."""
        # Prevent overlapping cycles (e.g. timer + manual /throne_refresh).
        async with self._poll_lock:
            event_cog = self.bot.get_cog("RobEventCog")
            if event_cog is not None and hasattr(event_cog, "ensure_event_state_current"):
                state = await event_cog.ensure_event_state_current()
                if not state.is_active:
                    return 0
            else:
                state = await self.database.get_event_state()
                if not state.is_active:
                    return 0

            profiles = await self.database.get_all_event_dommes()
            tracked = [
                p
                for p in profiles
                if p.throne_url
                and normalize_throne_url(p.throne_url) is not None
            ]
            if force_domme_user_id is not None:
                tracked = [p for p in tracked if p.user_id == force_domme_user_id]

            if not tracked:
                return 0

            # Light shuffle so a transient failure on one Domme doesn't
            # consistently block later ones in the list each cycle.
            if force_domme_user_id is None:
                random.shuffle(tracked)

            posted_total = 0
            for index, profile in enumerate(tracked):
                if force_domme_user_id is None and self._is_in_slow_retry(profile.user_id):
                    continue
                try:
                    posted_total += await self._poll_one_domme(profile)
                except Exception:  # noqa: BLE001
                    log.exception(
                        "Unexpected error polling Domme %s; continuing.",
                        profile.user_id,
                    )
                if index < len(tracked) - 1:
                    delay = self.config.throne_poll_per_domme_delay_seconds
                    if delay > 0:
                        # Add small jitter to avoid synchronised request bursts.
                        await asyncio.sleep(delay + random.uniform(0, delay / 2))

            if posted_total > 0:
                event_cog = self.bot.get_cog("RobEventCog")
                if event_cog is not None and hasattr(event_cog, "sync_leaderboard_channel"):
                    try:
                        await event_cog.sync_leaderboard_channel()
                    except Exception:  # noqa: BLE001
                        log.exception("Failed to sync leaderboard channel after Throne poll.")

            return posted_total

    def _is_in_slow_retry(self, domme_user_id: int) -> bool:
        until = self._slow_retry_until.get(domme_user_id)
        if until is None:
            return False
        if time.monotonic() >= until:
            self._slow_retry_until.pop(domme_user_id, None)
            return False
        return True

    def _record_failure(self, domme_user_id: int) -> None:
        count = self._failure_counts.get(domme_user_id, 0) + 1
        self._failure_counts[domme_user_id] = count
        if count == _FAILURE_THRESHOLD:
            self._slow_retry_until[domme_user_id] = (
                time.monotonic() + _SLOW_RETRY_INTERVAL_S
            )
            log.warning(
                "Throne scraping for Domme %s failed %s times in a row; "
                "backing off to 1-hour retry.",
                domme_user_id,
                count,
            )

    def _record_success(self, domme_user_id: int) -> None:
        if domme_user_id in self._failure_counts:
            self._failure_counts.pop(domme_user_id, None)
        self._slow_retry_until.pop(domme_user_id, None)

    async def _poll_one_domme(self, profile: EventDommeRegistration) -> int:
        """Poll a single Domme; returns number of new sends posted."""
        assert profile.throne_url is not None  # filtered above
        http = await self._get_http()
        scraped = await fetch_recent_sends(
            profile.throne_url,
            http=http,
            user_agent=self.config.throne_user_agent,
            timeout_seconds=self.config.throne_http_timeout_seconds,
        )
        if scraped is None:
            self._record_failure(profile.user_id)
            return 0
        self._record_success(profile.user_id)
        if not scraped:
            return 0

        # First-run baseline: if we've never seen any sends for this Domme,
        # store the current page as seeded (claim/leaderboard counts still
        # update) but do not post notification cards.
        is_first_run = not await self.database.has_any_event_sends_for_domme(
            domme_user_id=profile.user_id
        )

        known_external_ids = await self.database.get_known_event_external_ids_for_domme(
            domme_user_id=profile.user_id
        )

        new_items: list[ScrapedSend] = [
            item for item in scraped if item.external_id not in known_external_ids
        ]
        if not new_items:
            return 0

        # Process in chronological order (parser already sorts oldest first).
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
            )
            if send_id is None or is_first_run:
                # Either skipped due to duplicate external_id, or this is the
                # baseline seed for a brand-new Domme — don't post a card.
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
            log.warning(
                "Send-track channel %s is not a text channel; cannot post send card.",
                self.config.send_track_channel_id,
            )
            return
        send = await self.database.get_event_send(send_id=send_id)
        if send is None:
            return
        # Resolve the Domme as a member if possible for a nicer mention.
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
        sub_rank = (
            await self.database.get_event_sub_rank(user_id=send.claimed_sub_user_id)
            if send.claimed_sub_user_id is not None
            else None
        )
        domme_totals = await self.database.get_event_domme_total(user_id=domme_user_id)
        sub_label = sub_member.mention if sub_member is not None else "Unclaimed Send"
        domme_label = domme.mention if domme is not None else f"<@{domme_user_id}>"
        amount_label = format_money(send.amount_usd) if not send.is_private else "Unknown"
        try:
            await channel.send(
                view=SendNotificationView(
                    sub_label=sub_label,
                    domme_label=domme_label,
                    amount_label=amount_label,
                    item_name=send.item_name,
                    item_image_url=send.item_image_url,
                    sub_rank=sub_rank,
                    domme_send_count=domme_totals.send_count,
                )
            )
        except discord.HTTPException:
            log.exception(
                "Failed to post send notification for send id %s in channel %s.",
                send_id,
                self.config.send_track_channel_id,
            )
