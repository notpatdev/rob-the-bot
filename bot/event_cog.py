"""Event and leaderboard runtime for Rob the Bot."""
from __future__ import annotations

import asyncio
import logging
import random
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.config import BotConfig
from bot.database import Database, EventState, SendSummary, ThroneWishlistItem
from bot.deny import send_deny_response
from bot.event_config import ConfiguredEvent, EventTheme, EventsConfig, load_events_config
from bot.event_views import (
    DommeSignupModal,
    EventStatusView,
    FinalReportSummaryView,
    LeaderboardView,
    SubSignupModal,
    UpdateNotificationView,
    format_money,
    format_timestamp,
)
from bot.throne_scraper import (
    fetch_public_wishlist_items,
    normalize_throne_registration_input,
    resolve_creator_id,
    resolve_creator_info,
)
from bot.ui.cards import info_view, success_view
from bot.ui.copy import STATUS_LINES
from bot.utils import has_admin_command_permissions

log = logging.getLogger(__name__)

_RESERVED_SUB_NAMES = {"anonymous", "unclaimed send", "unclaimed"}
_MANUAL_SEND_SUB_FALLBACK = "Sub with no nickname claimed"
_MANUAL_SEND_METHODS = ("cashapp", "venmo", "paypal", "onlyfans", "loyalfans", "youpay", "other")
_REQUEST_SEND_METHODS = _MANUAL_SEND_METHODS + ("throne",)
_SEND_REQUEST_RATE_LIMIT = 3
_SEND_REQUEST_ADD_HINT_TEMPLATE = (
    "If this is real, run `/add amount:{amount:.2f} method:{method} sub:{sub}` "
    "to log it on the leaderboard {hint}"
)


class SendRequestDecisionView(discord.ui.View):
    def __init__(
        self,
        *,
        cog: "RobEventCog",
        request_id: int,
        target_domme_id: int,
        sub_display_name: str,
    ) -> None:
        super().__init__(timeout=60 * 60 * 24)
        self.cog = cog
        self.request_id = request_id
        self.target_domme_id = target_domme_id
        self.sub_display_name = sub_display_name

    async def _ensure_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.target_domme_id:
            return True
        await interaction.response.send_message("That button is not for you.", ephemeral=True)
        return False

    @discord.ui.button(label="Approve & Log", style=discord.ButtonStyle.success)
    async def approve_and_log(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if not await self._ensure_owner(interaction):
            return

        request = await self.cog.database.get_send_request(request_id=self.request_id)
        if request is None:
            await interaction.response.edit_message(content="Request not found.", view=None)
            return
        if request.status != "pending":
            await interaction.response.edit_message(
                content=f"Request already resolved as `{request.status}`.",
                view=None,
            )
            return

        tracker_cog = self.cog.bot.get_cog("ThroneTrackerCog")
        if tracker_cog is None:
            await interaction.response.send_message("Rob lost the send logger. Try again in a minute.", ephemeral=True)
            return

        context = await self.cog.get_runtime_context()
        event_key = context.event_key if context.is_event_active else None
        item_name = (request.note or "").strip() or f"Manual send via {request.method}"
        result = await tracker_cog.record_send(
            domme_user_id=request.domme_user_id,
            sub_name=self.sub_display_name or _MANUAL_SEND_SUB_FALLBACK,
            amount_usd=request.amount_usd,
            item_name=item_name,
            item_image_url=None,
            source=f"request:{request.method}",
            is_private=False,
            event_key=event_key,
        )
        if result is None:
            await interaction.response.send_message("That send could not be logged right now.", ephemeral=True)
            return

        _, send_public_id = result
        await self.cog.database.resolve_send_request(request_id=request.id, status="approved")
        await interaction.response.edit_message(content=f"✅ Logged as send #{send_public_id}.", view=None)

    @discord.ui.button(label="Ignore", style=discord.ButtonStyle.secondary)
    async def ignore(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if not await self._ensure_owner(interaction):
            return

        request = await self.cog.database.get_send_request(request_id=self.request_id)
        if request is not None and request.status == "pending":
            await self.cog.database.resolve_send_request(request_id=request.id, status="ignored")
        await interaction.response.edit_message(content="❌ Ignored.", view=None)


@dataclass(frozen=True)
class EventRuntimeContext:
    active_state: EventState | None
    active_event: ConfiguredEvent | None
    theme: EventTheme
    source_path: Path

    @property
    def is_event_active(self) -> bool:
        return self.active_event is not None and self.active_state is not None and self.active_state.is_active

    @property
    def event_key(self) -> str | None:
        return self.active_event.key if self.active_event is not None else None

    @property
    def display_title(self) -> str:
        return f"{self.theme.emoji} {self.theme.leaderboard_title}"


class RobEventCog(commands.Cog):
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
        self._synced_on_ready = False
        self._lifecycle_lock = asyncio.Lock()
        self._overlap_warning_keys: tuple[str, ...] | None = None
        self._warned_runtime_targets: set[str] = set()
        self.events_config: EventsConfig = load_events_config(self.config.events_config_path)
        self.status_loop.start()
        self.event_lifecycle_loop.start()

    def cog_unload(self) -> None:
        self.status_loop.cancel()
        self.event_lifecycle_loop.cancel()
        if self._http is not None and not self._http.closed:
            self.bot.loop.create_task(self._http.close())

    async def _get_http(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession()
        return self._http

    @staticmethod
    def _format_discord_timestamp(moment: datetime) -> str:
        ts = int(moment.timestamp())
        return f"<t:{ts}:R> / <t:{ts}:f>"

    def _warn_once(self, key: str, message: str, *args: object) -> None:
        if key in self._warned_runtime_targets:
            return
        self._warned_runtime_targets.add(key)
        log.warning(message, *args)

    def _active_configured_event(self, now: datetime) -> ConfiguredEvent | None:
        active = self.events_config.active_events(now)
        if len(active) > 1:
            keys = tuple(event.key for event in active)
            if keys != self._overlap_warning_keys:
                log.warning(
                    "Multiple events are active at once (%s). Rob will use the first one in config order.",
                    ", ".join(keys),
                )
                self._overlap_warning_keys = keys
        else:
            self._overlap_warning_keys = None
        return active[0] if active else None

    async def reload_events_config(self) -> None:
        self.events_config = load_events_config(self.config.events_config_path)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._synced_on_ready:
            return
        self._synced_on_ready = True
        await self._log_startup_configuration_warnings()
        context = await self.ensure_event_state_current(sync_leaderboard=False)
        await self.sync_leaderboard_channel(context=context)
        await self._notify_owner_on_start()

    async def _log_startup_configuration_warnings(self) -> None:
        if not self.config.guild_id:
            self._warn_once("guild_id", "GUILD_ID is missing in bot/channels.py. Rob cannot resolve guild resources yet.")
            return

        guild = self.bot.get_guild(self.config.guild_id)
        if guild is None:
            self._warn_once(
                "guild_lookup",
                "Configured guild %s is not available to the bot yet. Channel and role checks will wait.",
                self.config.guild_id,
            )
            return

        channel_targets = {
            "registration_channel_id": self.config.registration_channel_id,
            "leaderboard_channel_id": self.config.leaderboard_channel_id,
            "send_track_channel_id": self.config.send_track_channel_id,
        }
        for name, channel_id in channel_targets.items():
            if not channel_id:
                self._warn_once(name, "%s is missing in bot/channels.py.", name.upper())
                continue
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                self._warn_once(name, "Configured channel id %s for %s was not found as a text channel.", channel_id, name)

        role_targets = {
            "moderation_role_id": self.config.moderation_role_id,
            "domme_role_id": self.config.domme_role_id,
            "submissive_role_id": self.config.submissive_role_id,
        }
        for name, role_id in role_targets.items():
            if not role_id:
                self._warn_once(name, "%s is missing in bot/channels.py.", name.upper())
                continue
            if guild.get_role(role_id) is None:
                self._warn_once(name, "Configured role id %s for %s was not found in guild %s.", role_id, name, guild.id)

    async def _notify_owner_on_start(self) -> None:
        try:
            app = await self.bot.application_info()
            owner = app.owner
            if owner is None:
                return
            await owner.send(view=UpdateNotificationView())
            log.info("Sent startup notification to owner %s.", owner)
        except discord.HTTPException:
            log.warning("Could not DM bot owner on startup.", exc_info=True)

    @tasks.loop(minutes=12)
    async def status_loop(self) -> None:
        try:
            await self.bot.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.watching,
                    name=random.choice(STATUS_LINES),
                )
            )
        except discord.HTTPException:
            log.warning("Failed to update status.", exc_info=True)

    @status_loop.before_loop
    async def _before_status_loop(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def event_lifecycle_loop(self) -> None:
        await self.ensure_event_state_current(sync_leaderboard=True)

    @event_lifecycle_loop.before_loop
    async def _before_event_lifecycle_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def ensure_event_state_current(self, *, sync_leaderboard: bool = True) -> EventRuntimeContext:
        async with self._lifecycle_lock:
            now = datetime.now(timezone.utc)
            active_event = self._active_configured_event(now)
            active_state = await self.database.get_active_event_state()
            lifecycle_changed = False

            if active_state is not None and (active_event is None or active_state.event_key != active_event.key):
                active_state = await self.database.end_event(
                    event_key=active_state.event_key,
                    ended_by=None,
                    ended_at=now.isoformat(),
                )
                lifecycle_changed = True
                active_state = None

            if active_event is not None:
                start_at = active_event.start_at.isoformat() if active_event.start_at is not None else None
                end_at = active_event.end_at.isoformat() if active_event.end_at is not None else None
                if (
                    active_state is None
                    or active_state.event_key != active_event.key
                    or active_state.event_name != active_event.name
                    or active_state.starts_at != start_at
                    or active_state.ends_at != end_at
                    or not active_state.is_active
                ):
                    active_state = await self.database.activate_event(
                        event_key=active_event.key,
                        event_name=active_event.name,
                        starts_at=start_at,
                        ends_at=end_at,
                        started_by=None,
                    )
                    lifecycle_changed = True

            context = EventRuntimeContext(
                active_state=active_state,
                active_event=active_event,
                theme=active_event.theme if active_event is not None else self.events_config.default_theme,
                source_path=self.events_config.source_path,
            )

            pending_reports = await self.database.get_pending_event_reports()
            if pending_reports:
                lifecycle_changed = True
                for state in pending_reports:
                    await self._post_final_event_report(state)

            if sync_leaderboard and lifecycle_changed:
                await self._sync_leaderboard_channel(context)

            return context

    async def get_runtime_context(self) -> EventRuntimeContext:
        return await self.ensure_event_state_current(sync_leaderboard=False)

    async def get_signup_block_reason(
        self,
        interaction: discord.Interaction,
        *,
        signup_type: str,
    ) -> str | None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return "Server only."
        member = interaction.user
        if self._member_has_role(member, self.config.event_ban_role_id):
            return "Nope. You're blocked from this event."
        if signup_type == "domme" and self._member_has_role(member, self.config.submissive_role_id):
            return "You already have the Sub role."
        if signup_type == "sub" and self._member_has_role(member, self.config.domme_role_id):
            return "You already have the Domme role."
        return None

    @staticmethod
    def _member_has_role(member: discord.Member, role_id: int) -> bool:
        return role_id > 0 and any(role.id == role_id for role in member.roles)

    async def _is_registered_domme(self, *, member: discord.Member) -> bool:
        if self._member_has_role(member, self.config.domme_role_id):
            return True
        guild_id = str(member.guild.id) if member.guild is not None else str(self.config.guild_id or 0)
        creator = await self.database.get_throne_creator_by_discord_user(
            guild_id=guild_id,
            discord_user_id=str(member.id),
        )
        return creator is not None

    @commands.group(name="event", invoke_without_command=True)
    async def event_group(self, ctx: commands.Context[commands.Bot]) -> None:
        await ctx.reply(
            "Rob knows: `!event status` `!event reload` `!event start` `!event end`",
            mention_author=False,
        )

    @event_group.command(name="start")
    async def event_start(self, ctx: commands.Context[commands.Bot]) -> None:
        if not await self._check_admin_context(ctx):
            return
        await ctx.reply(
            view=info_view(
                "Events live in `config/events.json` now.",
                "Set `enabled`, `start_at`, and `end_at`, then run `!event reload` or restart Rob.",
            ),
            mention_author=False,
        )

    @event_group.command(name="end")
    async def event_end(self, ctx: commands.Context[commands.Bot]) -> None:
        if not await self._check_admin_context(ctx):
            return
        await ctx.reply(
            view=info_view(
                "Events live in `config/events.json` now.",
                "To end one early, shorten `end_at` or disable it in the JSON, then run `!event reload`.",
            ),
            mention_author=False,
        )

    @event_group.command(name="reload")
    async def event_reload(self, ctx: commands.Context[commands.Bot]) -> None:
        if not await self._check_admin_context(ctx):
            return
        await self.reload_events_config()
        context = await self.ensure_event_state_current(sync_leaderboard=False)
        await self.sync_leaderboard_channel(context=context)
        mode = self._current_mode_label(context)
        await ctx.reply(
            view=success_view(
                "Reloaded.",
                f"Loaded `{self.events_config.source_path.as_posix()}`.\n\nCurrent mode: **{mode}**",
            ),
            mention_author=False,
        )

    @event_group.command(name="status")
    async def event_status(self, ctx: commands.Context[commands.Bot]) -> None:
        if not await self._check_admin_context(ctx):
            return

        context = await self.get_runtime_context()
        live_summary = await self.database.get_send_summary(event_key=None)
        domme_count = len(await self.database.get_all_event_dommes())
        sub_count = await self.database.count_event_sub_registrations()
        now = datetime.now(timezone.utc)

        configured_events: list[str] = []
        for event in self.events_config.events:
            if not event.enabled:
                configured_events.append(f"{event.theme.emoji} {event.name} — disabled")
                continue
            if not event.is_config_complete:
                configured_events.append(f"{event.theme.emoji} {event.name} — enabled, missing dates")
                continue
            assert event.start_at is not None and event.end_at is not None
            if event.is_active(now):
                configured_events.append(
                    f"{event.theme.emoji} {event.name} — active until "
                    f"<t:{int(event.end_at.timestamp())}:R> / <t:{int(event.end_at.timestamp())}:f>"
                )
            elif now < event.start_at:
                configured_events.append(
                    f"{event.theme.emoji} {event.name} — scheduled for "
                    f"<t:{int(event.start_at.timestamp())}:R> / <t:{int(event.start_at.timestamp())}:f>"
                )
            else:
                configured_events.append(
                    f"{event.theme.emoji} {event.name} — ended "
                    f"<t:{int(event.end_at.timestamp())}:R> / <t:{int(event.end_at.timestamp())}:f>"
                )

        await ctx.reply(
            view=EventStatusView(
                source_path=self.events_config.source_path.as_posix(),
                current_mode=self._current_mode_label(context),
                default_theme_label=f"{self.events_config.default_theme.emoji} {self.events_config.default_theme.leaderboard_title}",
                configured_events=configured_events,
                domme_count=domme_count,
                sub_count=sub_count,
                live_send_count=live_summary.send_count,
                live_send_total=format_money(live_summary.total_usd),
            ),
            mention_author=False,
        )

    @commands.command(name="throne-blacklist")
    @commands.has_permissions(manage_guild=True)
    async def throne_blacklist(self, ctx: commands.Context, target: str) -> None:
        """Remove a user's Throne registration and add them to Rob's blacklist."""
        try:
            discord_user_id = str(int(target.strip("<@!>")))
        except ValueError:
            await ctx.reply("Invalid user id.", mention_author=False)
            return
    
        guild_id = str(ctx.guild.id) if ctx.guild else "0"
    
        removed_creator_id = await self.database.remove_throne_creator_by_discord_user(
            guild_id=guild_id, discord_user_id=discord_user_id
        )
        await self.database.add_to_blacklist(
            discord_user_id=discord_user_id,
            reason="throne blacklist",
            created_by=str(ctx.author.id),
        )
    
        if removed_creator_id is None:
            await ctx.reply(
                f"No Throne registration found for `{discord_user_id}`. Added to global blacklist.",
                mention_author=False,
            )
        else:
            await ctx.reply(
                f"Removed Throne registration `{removed_creator_id}` for `{discord_user_id}` and added them to the global blacklist. Historical sends are kept.",
                mention_author=False,
            )
    
    
    @commands.command(name="rob-blacklist")
    @commands.has_permissions(manage_guild=True)
    async def rob_blacklist(self, ctx: commands.Context, target: str, *, reason: str = "manual") -> None:
        """Add a user to Rob's silent blacklist."""
        try:
            discord_user_id = str(int(target.strip("<@!>")))
        except ValueError:
            await ctx.reply("Invalid user id.", mention_author=False)
            return
        await self.database.add_to_blacklist(
            discord_user_id=discord_user_id,
            reason=reason,
            created_by=str(ctx.author.id),
        )
        await ctx.reply(
            f"`{discord_user_id}` has been added to the blacklist. Silent.",
            mention_author=False,
        )
    
    
    @commands.command(name="rob-unblacklist")
    @commands.has_permissions(manage_guild=True)
    async def rob_unblacklist(self, ctx: commands.Context, target: str) -> None:
        """Remove a user from Rob's silent blacklist."""
        try:
            discord_user_id = str(int(target.strip("<@!>")))
        except ValueError:
            await ctx.reply("Invalid user id.", mention_author=False)
            return
        await self.database.remove_from_blacklist(discord_user_id=discord_user_id)
        await ctx.reply(
            f"`{discord_user_id}` has been removed from the blacklist.",
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

    @app_commands.command(name="register", description="Register for the event as a Domme or Sub.")
    @app_commands.describe(action="Choose whether you're signing up as a Domme or a Sub.")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Domme", value="domme"),
            app_commands.Choice(name="Sub", value="sub"),
        ]
    )
    async def register(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
    ) -> None:
        signup_type = action.value
        reason = await self.get_signup_block_reason(interaction, signup_type=signup_type)
        if reason is not None:
            await interaction.response.send_message(reason, ephemeral=True)
            return
        if signup_type == "domme":
            await interaction.response.send_modal(DommeSignupModal(self))
        else:
            await interaction.response.send_modal(SubSignupModal(self))

    @app_commands.command(name="add", description="Log a manual send to the leaderboard.")
    @app_commands.describe(
        amount="Amount sent in USD",
        method="Where the send happened",
        sub="Sub name/handle",
        note="Optional note for this send",
    )
    @app_commands.choices(method=[app_commands.Choice(name=value, value=value) for value in _MANUAL_SEND_METHODS])
    async def add_send(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[float, 0.01],
        method: app_commands.Choice[str],
        sub: str | None = None,
        note: str | None = None,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Server only.", ephemeral=True)
            return

        if not await self._is_registered_domme(member=interaction.user):
            await interaction.response.send_message("Only registered Dommes can use this command.", ephemeral=True)
            return

        tracker_cog = self.bot.get_cog("ThroneTrackerCog")
        if tracker_cog is None:
            await interaction.response.send_message("Rob lost the send logger. Try again in a minute.", ephemeral=True)
            return

        context = await self.get_runtime_context()
        event_key = context.event_key if context.is_event_active else None
        clean_sub = (sub or "").strip() or _MANUAL_SEND_SUB_FALLBACK
        item_name = (note or "").strip() or f"Manual send via {method.value}"
        result = await tracker_cog.record_send(
            domme_user_id=interaction.user.id,
            sub_name=clean_sub,
            amount_usd=float(amount),
            item_name=item_name,
            item_image_url=None,
            source=f"manual:{method.value}",
            is_private=False,
            event_key=event_key,
        )
        if result is None:
            await interaction.response.send_message("That send could not be recorded right now.", ephemeral=True)
            return

        _, send_public_id = result
        await interaction.response.send_message(
            f"✅ Recorded send `{send_public_id}` for **{format_money(float(amount))}** via `{method.value}`.",
            ephemeral=True,
        )

    @app_commands.command(name="sendrequest", description="Request a Domme to log a send you made.")
    @app_commands.describe(
        domme="Domme you sent to",
        amount="Amount sent in USD",
        method="Where the send happened",
        note="Optional context (screenshot URL, message, etc.)",
    )
    @app_commands.choices(method=[app_commands.Choice(name=value, value=value) for value in _REQUEST_SEND_METHODS])
    async def send_request(
        self,
        interaction: discord.Interaction,
        domme: discord.Member,
        amount: app_commands.Range[float, 0.01],
        method: app_commands.Choice[str],
        note: str | None = None,
    ) -> None:
        blocked = await self.database.is_user_blacklisted(discord_user_id=str(interaction.user.id))
        if blocked:
            await send_deny_response(interaction)
            return

        if interaction.guild is None:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return

        if not await self._is_registered_domme(member=domme):
            await interaction.response.send_message("That user isn't a registered domme.", ephemeral=True)
            return

        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        recent_count = await self.database.count_send_requests_since(
            sub_user_id=interaction.user.id,
            domme_user_id=domme.id,
            since=since,
        )
        if recent_count >= _SEND_REQUEST_RATE_LIMIT:
            await interaction.response.send_message(
                f"You hit the limit for send requests to this domme ({_SEND_REQUEST_RATE_LIMIT} per 24h).",
                ephemeral=True,
            )
            return

        trimmed_note = (note or "").strip() or None
        request_id = await self.database.create_send_request(
            sub_user_id=interaction.user.id,
            domme_user_id=domme.id,
            amount_usd=float(amount),
            method=method.value,
            note=trimmed_note,
        )

        sub_display_name = interaction.user.display_name
        # `/add` intentionally excludes `throne` because webhook sends are normally
        # automatic, so throne requests map to `other` when manually logging.
        suggested_method = method.value if method.value in _MANUAL_SEND_METHODS else "other"
        method_hint = "(`throne` requests should be logged as `other` in /add)." if method.value == "throne" else ""
        add_hint = _SEND_REQUEST_ADD_HINT_TEMPLATE.format(
            amount=float(amount),
            method=suggested_method,
            sub=sub_display_name,
            hint=method_hint,
        ).rstrip()
        dm_message = (
            f"💌 **Send Request from `{sub_display_name}`** (`{interaction.user.id}`)\n"
            f"**Amount:** {format_money(float(amount))}\n"
            f"**Method:** {method.value}\n"
            f"**Note:** {trimmed_note or '—'}\n\n"
            f"{add_hint}"
        )

        try:
            await domme.send(
                dm_message,
                view=SendRequestDecisionView(
                    cog=self,
                    request_id=request_id,
                    target_domme_id=domme.id,
                    sub_display_name=sub_display_name,
                ),
            )
        except (discord.Forbidden, discord.HTTPException):
            await self.database.delete_send_request(request_id=request_id)
            await interaction.response.send_message(
                "Couldn't deliver that request to the domme's DMs.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Sent your request to {domme.mention}. They'll review and decide whether to log it.",
            ephemeral=True,
        )

    async def process_domme_signup(
        self,
        interaction: discord.Interaction,
        raw_value: str,
    ) -> None:
        reason = await self.get_signup_block_reason(interaction, signup_type="domme")
        if reason is not None:
            await interaction.response.send_message(reason, ephemeral=True)
            return

        normalized = normalize_throne_registration_input(raw_value)
        if normalized is None:
            await interaction.response.send_message(
                "That link looks wrong. Try a full Throne link or username.",
                ephemeral=True,
            )
            return

        http = await self._get_http()

        # Resolve full creator info (id + handle + hideOwnPurchases).
        creator_info = await resolve_creator_info(
            normalized,
            http=http,
            timeout_seconds=self.config.throne_http_timeout_seconds,
        )
        if creator_info is None:
            await interaction.response.send_message(
                "Rob squinted at that link and found nothing. Check it and try again.",
                ephemeral=True,
            )
            return

        # Determine guild_id (may be None in DMs, but signup requires a guild).
        guild_id = str(interaction.guild_id) if interaction.guild_id else "0"
        discord_user_id = str(interaction.user.id)

        # Preserve existing webhook_secret if the creator is already registered.
        existing = await self.database.get_throne_creator_by_handle(
            guild_id=guild_id,
            throne_handle=creator_info.throne_handle,
        )
        if existing is not None and existing.webhook_secret:
            webhook_secret = existing.webhook_secret
        else:
            webhook_secret = secrets.token_urlsafe(32)

        # Webhook-only flow: keep connected creators as webhook, otherwise wait
        # for the user's first successful webhook event / test.
        if existing is not None and existing.tracking_mode == "webhook":
            tracking_mode = "webhook"
        else:
            tracking_mode = "disabled"

        throne_creator = await self.database.upsert_throne_creator(
            guild_id=guild_id,
            discord_user_id=discord_user_id,
            throne_handle=creator_info.throne_handle,
            throne_creator_id=creator_info.creator_id,
            hide_own_purchases=creator_info.hide_own_purchases,
            tracking_mode=tracking_mode,
            webhook_secret=webhook_secret,
            overlay_detected=False,
            last_overlay_check_at=None,
        )

        wishlist_items = await fetch_public_wishlist_items(
            creator_info.creator_id,
            http=http,
            timeout_seconds=self.config.throne_http_timeout_seconds,
        )
        if wishlist_items is not None:
            now_str = datetime.now(timezone.utc).isoformat()
            await self.database.replace_throne_wishlist_items(
                creator_id=creator_info.creator_id,
                items=[
                    ThroneWishlistItem(
                        creator_id=creator_info.creator_id,
                        wishlist_item_id=item.wishlist_item_id,
                        item_name=item.item_name,
                        item_image_url=item.item_image_url,
                        amount_usd=item.amount_usd,
                        currency=item.currency,
                        is_available=item.is_available,
                        last_seen_at=now_str,
                    )
                    for item in wishlist_items
                ],
            )

        # Save to event_dommes as before (keeps leaderboard / existing flows working).
        await self.database.save_event_domme(user_id=interaction.user.id, throne_url=normalized)
        await self.sync_leaderboard_channel()

        # Build the webhook URL if the base URL is configured.
        webhook_url: str | None = None
        base_url = self.config.throne_webhook_base_url
        if base_url:
            base_url = base_url.rstrip("/")
            webhook_url = f"{base_url}/throne/webhook/{creator_info.creator_id}/{throne_creator.webhook_secret}"

        # Compose ephemeral reply.
        mode_labels = {
            "webhook": "🟢 Webhook connected",
            "disabled": "🟡 Waiting for webhook setup",
        }
        mode_label = mode_labels.get(tracking_mode, tracking_mode)

        lines: list[str] = [
            f"✅ Linked **{creator_info.throne_handle}**.",
            f"**Tracking mode:** {mode_label}",
        ]

        if tracking_mode == "disabled":
            if webhook_url:
                lines.append(
                    "\nGo to **Throne → Settings → Integrations → Webhooks**, paste this URL, "
                    "save it, then click **Test Webhook**:"
                )
                lines.append(f"`{webhook_url}`")
            else:
                lines.append(
                    "\nWebhook tracking is ready on Rob's side, but `THRONE_WEBHOOK_BASE_URL` "
                    "is not configured yet, so there is no URL to paste into Throne."
                )
        elif webhook_url:
            lines.append(f"\n**Webhook URL:** `{webhook_url}`")

        await interaction.response.send_message(
            view=success_view("Handled.", "\n".join(lines)),
            ephemeral=True,
        )

    async def process_sub_signup(
        self,
        interaction: discord.Interaction,
        raw_name: str,
    ) -> None:
        reason = await self.get_signup_block_reason(interaction, signup_type="sub")
        if reason is not None:
            await interaction.response.send_message(reason, ephemeral=True)
            return

        sub_name = " ".join(raw_name.strip().split())
        if not sub_name:
            await interaction.response.send_message("Need a name to track.", ephemeral=True)
            return
        if sub_name.casefold() in _RESERVED_SUB_NAMES:
            await interaction.response.send_message("That name is reserved. Pick another one.", ephemeral=True)
            return

        existing = await self.database.get_event_sub_by_name(sub_name=sub_name)
        if existing is not None and existing.user_id != interaction.user.id:
            await interaction.response.send_message("That name is taken already.", ephemeral=True)
            return

        await self.database.save_event_sub(user_id=interaction.user.id, sub_name=sub_name)
        await self.sync_leaderboard_channel()
        await interaction.response.send_message(
            view=success_view(
                "Handled.",
                (
                    f"Tracking name: **{sub_name}**.\n\n"
                    "Use that exact name on Throne and Rob will do the maths."
                ),
            ),
            ephemeral=True,
        )

    async def sync_leaderboard_channel(self, *, context: EventRuntimeContext | None = None) -> None:
        if context is None:
            context = await self.get_runtime_context()
        await self._sync_leaderboard_channel(context)

    async def _sync_leaderboard_channel(self, context: EventRuntimeContext) -> None:
        guild = self.bot.get_guild(self.config.guild_id)
        if guild is None:
            return
        channel = guild.get_channel(self.config.leaderboard_channel_id)
        if not isinstance(channel, discord.TextChannel):
            self._warn_once(
                "leaderboard_channel_runtime",
                "Leaderboard channel id %s is not available as a text channel.",
                self.config.leaderboard_channel_id,
            )
            return

        if await self._leaderboard_messages_need_reorder(channel):
            await self._clear_leaderboard_messages(channel)

        event_key = context.event_key
        sub_rows_db = await self.database.get_event_sub_totals(limit=20, offset=0, event_key=event_key)
        domme_rows_db = await self.database.get_event_domme_totals(event_key=event_key)
        unclaimed_total = await self.database.get_event_unclaimed_total(event_key=event_key)
        unclaimed_rows_db = await self.database.get_unclaimed_send_rows(limit=8, event_key=event_key)

        domme_rows = [(f"<@{row.user_id}>", row.total_usd, row.send_count) for row in domme_rows_db]
        sub_rows = [(f"<@{row.user_id}>", row.total_usd, row.send_count) for row in sub_rows_db]
        unclaimed_rows = [(row.sub_name, row.total_usd, row.send_count) for row in unclaimed_rows_db]

        status_lines = self._leaderboard_status_lines(context)
        domme_helper = [
            "Use the Link Throne button and hand Rob your Throne link. He cannot track sends by spiritual connection."
        ]
        sub_helper = [
            "Use the Claim Sends button and give Rob your exact Throne sending name. Then he does the maths and fixes your rank."
        ]

        domme_view = LeaderboardView(
            cog=self,
            title="🏆 Rob | Leaderboards | Dommes",
            board_title=None,
            status_lines=status_lines,
            rows=domme_rows,
            empty_message="No sends recorded yet. Quiet board, for now.",
            accent_color=context.theme.accent_color,
            register_kind="domme",
            register_button_label="Link Throne",
            register_section_text="Link your Throne and let Rob drag your sends onto the board.",
            helper_lines=domme_helper,
            footer=self._leaderboard_footer(context),
        )
        sub_view = LeaderboardView(
            cog=self,
            title="🏆 Rob | Leaderboards | Subs",
            board_title=None,
            status_lines=status_lines,
            rows=sub_rows,
            empty_message="Nobody is on the board yet. Suspiciously peaceful.",
            accent_color=context.theme.accent_color,
            register_kind="sub",
            register_button_label="Claim Sends",
            register_section_text="If you have sends waiting to be claimed, click the button and enter the exact sending name you use on Throne when prompted.",
            unclaimed_rows=unclaimed_rows,
            unclaimed_total=format_money(unclaimed_total),
            helper_lines=sub_helper,
            footer=self._leaderboard_footer(context),
        )

        await self._upsert_channel_message(
            message_key="event:domme_totals",
            channel=channel,
            view=domme_view,
        )
        await self._upsert_channel_message(
            message_key="event:sub_leaderboard",
            channel=channel,
            view=sub_view,
        )

    async def _leaderboard_messages_need_reorder(self, channel: discord.TextChannel) -> bool:
        domme_ref = await self.database.get_event_message(message_key="event:domme_totals")
        sub_ref = await self.database.get_event_message(message_key="event:sub_leaderboard")
        if domme_ref is None or sub_ref is None:
            return False
        domme_id, domme_channel_id = domme_ref
        sub_id, sub_channel_id = sub_ref
        return domme_channel_id == channel.id and sub_channel_id == channel.id and domme_id > sub_id

    async def _clear_leaderboard_messages(self, channel: discord.TextChannel) -> None:
        for key in ("event:domme_totals", "event:sub_leaderboard"):
            existing = await self.database.get_event_message(message_key=key)
            if existing is None:
                continue
            message_id, channel_id = existing
            if channel_id != channel.id:
                continue
            try:
                message = await channel.fetch_message(message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue
            try:
                await message.delete()
            except (discord.Forbidden, discord.HTTPException):
                pass

    async def _upsert_channel_message(
        self,
        *,
        message_key: str,
        channel: discord.TextChannel,
        view: discord.ui.LayoutView,
    ) -> discord.Message | None:
        existing = await self.database.get_event_message(message_key=message_key)
        message: discord.Message | None = None
        if existing is not None:
            message_id, channel_id = existing
            if channel_id == channel.id:
                try:
                    message = await channel.fetch_message(message_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    message = None

        try:
            if message is None:
                message = await channel.send(view=view)
            else:
                await message.edit(view=view)
        except discord.HTTPException:
            log.exception("Failed to upsert message %s in channel %s.", message_key, channel.id)
            return None

        await self.database.upsert_event_message(
            message_key=message_key,
            message_id=message.id,
            channel_id=channel.id,
        )
        return message

    async def _post_final_event_report(self, state: EventState) -> None:
        guild = self.bot.get_guild(self.config.guild_id)
        if guild is None:
            return

        event = self.events_config.get_event(state.event_key)
        theme = event.theme if event is not None else self.events_config.default_theme
        channel = self._report_channel(guild)
        if channel is None:
            self._warn_once(
                f"report_channel_{state.event_key}",
                "No valid event report channel is configured. Rob will retry final report posting later.",
            )
            return

        summary = await self.database.get_send_summary(event_key=state.event_key)
        domme_rows_db = await self.database.get_event_domme_totals(event_key=state.event_key)
        sub_rows_db = await self.database.get_event_sub_totals(limit=50, offset=0, event_key=state.event_key)
        unclaimed_total = await self.database.get_event_unclaimed_total(event_key=state.event_key)

        domme_rows = [(f"<@{row.user_id}>", row.total_usd, row.send_count) for row in domme_rows_db]
        sub_rows = [(f"<@{row.user_id}>", row.total_usd, row.send_count) for row in sub_rows_db]

        title = "🏆 Rob | Leaderboards | Final Report"
        summary_view = FinalReportSummaryView(
            title=title,
            accent_color=theme.accent_color,
            event_key=state.event_key,
            started_at=self._format_iso_label(state.starts_at),
            ended_at=self._format_iso_label(state.ended_at or state.ends_at),
            total_send_amount=format_money(summary.total_usd),
            total_send_count=summary.send_count,
            dommes_ranked=len(domme_rows_db),
            subs_ranked=await self.database.count_event_ranked_subs(event_key=state.event_key),
            unclaimed_total=format_money(unclaimed_total),
            generated_at=self._format_iso_label(datetime.now(timezone.utc).isoformat()),
        )
        domme_view = LeaderboardView(
            title=title,
            board_title="Final Domme Leaderboard",
            status_lines=["🔒 Final results"],
            rows=domme_rows,
            empty_message="No sends were recorded for this event.",
            accent_color=theme.accent_color,
            footer=f"Event key: {state.event_key}",
        )
        sub_view = LeaderboardView(
            title=title,
            board_title="Final Sub Leaderboard",
            status_lines=["🔒 Final results"],
            rows=sub_rows,
            empty_message="Nobody landed on the sub board this round.",
            accent_color=theme.accent_color,
            helper_lines=[f"Unclaimed total: **{format_money(unclaimed_total)}**"] if unclaimed_total > 0.01 else None,
            footer=f"Event key: {state.event_key}",
        )

        views = (
            (f"event:{state.event_key}:final_report:summary", summary_view),
            (f"event:{state.event_key}:final_report:dommes", domme_view),
            (f"event:{state.event_key}:final_report:subs", sub_view),
        )
        for message_key, view in views:
            message = await self._upsert_channel_message(
                message_key=message_key,
                channel=channel,
                view=view,
            )
            if message is None:
                return

        await self.database.mark_event_report_posted(event_key=state.event_key)

    def _report_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        for channel_id in (self.config.event_report_channel_id, self.config.leaderboard_channel_id):
            if not channel_id:
                continue
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
                return channel
        return None

    def _leaderboard_status_lines(self, context: EventRuntimeContext) -> list[str]:
        if context.is_event_active and context.active_state is not None:
            status = ["🟢 Active"]
            if context.active_state.ends_at:
                try:
                    end_ts = int(datetime.fromisoformat(context.active_state.ends_at).timestamp())
                    status.append(f"Ends <t:{end_ts}:R> / <t:{end_ts}:f>")
                except ValueError:
                    pass
            return status
        return ["⚪ Live"]

    def _leaderboard_footer(self, context: EventRuntimeContext) -> str:
        if context.is_event_active and context.active_event is not None:
            return f"{context.active_event.name} is using the event board right now."
        return "Live board. Always on."

    def _current_mode_label(self, context: EventRuntimeContext) -> str:
        if context.is_event_active and context.active_event is not None:
            return f"{context.active_event.name} — active"
        return "Default live mode"

    def _format_iso_label(self, value: str | None) -> str:
        return format_timestamp(value)
