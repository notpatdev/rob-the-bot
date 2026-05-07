"""Event cog — Rob the Bot.

Commands
--------
DEV   !import id             — opens configuration modal (2-step)
MOD   !event start           — opens end-time picker
MOD   !event end             — confirms early end
MOD   !event status          — shows event state
USER  /register action:sub   — sub sign-up modal
USER  /register action:domme — domme sign-up modal
"""
from __future__ import annotations

import logging
import random
from dataclasses import replace
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.config import BotConfig
from bot.database import Database, EventState
from bot.event_views import (
    DommeSignupModal,
    DommeTotalsView,
    EventEndConfirmView,
    EventStartPromptView,
    EventStatusView,
    ImportPromptView,
    SubLeaderboardView,
    SubSignupModal,
    UpdateNotificationView,
    _simple_view,
    BLUE,
    GREEN,
)
from bot.throne_scraper import normalize_throne_registration_input, resolve_creator_id
from bot.utils import has_admin_command_permissions

log = logging.getLogger(__name__)

_RESERVED_SUB_NAMES = {"anonymous", "unclaimed send", "unclaimed"}
_EVENT_TIMEZONE = ZoneInfo("Australia/Sydney")
_EVENT_TIMEZONE_LABEL = "Australia/Sydney (AEST/AEDT)"


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
        self.status_loop.start()
        self.event_lifecycle_loop.start()

    # ──────────────────────────────── lifecycle ────────────────────────────────

    async def restore_runtime(self) -> None:
        """Load persisted config IDs from the database and apply them."""
        stored = await self.database.get_bot_config_ids()
        if stored:
            self.config = replace(self.config, **stored)
            self.bot.config = self.config  # keep bot.config in sync

    def cog_unload(self) -> None:
        self.status_loop.cancel()
        self.event_lifecycle_loop.cancel()
        if self._http is not None and not self._http.closed:
            self.bot.loop.create_task(self._http.close())

    async def _get_http(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession()
        return self._http

    def _server_name(self) -> str:
        guild = self.bot.get_guild(self.config.guild_id)
        return guild.name if guild is not None else self.config.bot_name

    @staticmethod
    def _format_discord_timestamp(moment: datetime) -> str:
        ts = int(moment.timestamp())
        return f"<t:{ts}:F> (<t:{ts}:R>)"

    def _parse_end_datetime(self, *, end_date: str, end_time: str) -> datetime | None:
        try:
            date_part = datetime.strptime(end_date.strip(), "%Y-%m-%d").date()
            time_part = datetime.strptime(end_time.strip(), "%H:%M").time()
        except ValueError:
            return None
        local = datetime.combine(date_part, time_part, tzinfo=_EVENT_TIMEZONE)
        return local.astimezone(timezone.utc)

    @staticmethod
    def _member_has_role(member: discord.Member, role_id: int) -> bool:
        return role_id > 0 and any(r.id == role_id for r in member.roles)

    # ──────────────────────────────── listeners ────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._synced_on_ready:
            return
        self._synced_on_ready = True
        await self.ensure_event_state_current()
        await self.sync_leaderboard_channel()
        await self._notify_owner_on_start()

    async def _notify_owner_on_start(self) -> None:
        """DM the application owner an update-complete notification."""
        try:
            app = await self.bot.application_info()
            owner = app.owner
            if owner is None:
                return
            await owner.send(view=UpdateNotificationView())
            log.info("Sent startup notification to owner %s.", owner)
        except discord.HTTPException:
            log.warning("Could not DM bot owner on startup.", exc_info=True)

    # ──────────────────────────────── background loops ─────────────────────────

    @tasks.loop(minutes=12)
    async def status_loop(self) -> None:
        statuses = [
            self.config.event_name,
            "send totals",
            "Throne again",
            "everyone's leaderboard business",
        ]
        try:
            await self.bot.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.watching,
                    name=random.choice(statuses),
                )
            )
        except discord.HTTPException:
            log.warning("Failed to update status.", exc_info=True)

    @status_loop.before_loop
    async def _before_status_loop(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def event_lifecycle_loop(self) -> None:
        await self.ensure_event_state_current()

    @event_lifecycle_loop.before_loop
    async def _before_event_lifecycle_loop(self) -> None:
        await self.bot.wait_until_ready()

    # ──────────────────────────────── helpers ──────────────────────────────────

    async def ensure_event_state_current(self) -> EventState:
        state = await self.database.get_event_state()
        if not state.is_active or not state.ends_at:
            return state
        try:
            ends_at = datetime.fromisoformat(state.ends_at)
        except ValueError:
            return state
        if ends_at <= datetime.now(timezone.utc):
            state = await self.database.end_event(ended_by=None)
            await self.sync_leaderboard_channel()
        return state

    async def get_signup_block_reason(
        self,
        interaction: discord.Interaction,
        *,
        signup_type: str,
    ) -> str | None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return "This sign-up only works in the server."
        member = interaction.user
        state = await self.ensure_event_state_current()
        if not state.is_active and state.ended_at is not None:
            return "The event has ended."
        if self._member_has_role(member, self.config.event_ban_role_id):
            return "You can't register for this event."
        if signup_type == "domme" and self._member_has_role(member, self.config.submissive_role_id):
            return "You can't sign up as a Domme while you have the Sub role."
        if signup_type == "sub" and self._member_has_role(member, self.config.domme_role_id):
            return "You can't sign up as a Sub while you have the Domme role."
        return None

    # ──────────────────────────────── !import id ──────────────────────────────

    @commands.command(name="import")
    async def import_ids(self, ctx: commands.Context[commands.Bot]) -> None:
        """DEV: open a form to set channel and role IDs."""
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.reply("This command only works in a server channel.", mention_author=False)
            return

        # Gate on bot application owner only
        try:
            app = await self.bot.application_info()
            owner_id = app.owner.id if app.owner else None
        except discord.HTTPException:
            owner_id = None

        if owner_id is None or ctx.author.id != owner_id:
            # Allow server admins as a fallback if owner is not present
            if not ctx.author.guild_permissions.administrator:
                await ctx.reply("Only the bot owner or a server administrator can use this command.", mention_author=False)
                return

        guild_id = ctx.guild.id
        view = ImportPromptView(self, owner_id=ctx.author.id, guild_id=guild_id)
        await ctx.reply(view=view, mention_author=False)

    async def save_config_ids(
        self,
        interaction: discord.Interaction,
        *,
        guild_id: int,
        registration_channel_id: int,
        leaderboard_channel_id: int,
        send_track_channel_id: int,
        moderation_role_id: int,
        domme_role_id: int,
        submissive_role_id: int,
        event_ban_role_id: int,
    ) -> None:
        await self.database.save_bot_config_ids(
            guild_id=guild_id,
            registration_channel_id=registration_channel_id,
            leaderboard_channel_id=leaderboard_channel_id,
            send_track_channel_id=send_track_channel_id,
            moderation_role_id=moderation_role_id,
            domme_role_id=domme_role_id,
            submissive_role_id=submissive_role_id,
            event_ban_role_id=event_ban_role_id,
        )
        self.config = replace(
            self.config,
            guild_id=guild_id or self.config.guild_id,
            registration_channel_id=registration_channel_id or self.config.registration_channel_id,
            leaderboard_channel_id=leaderboard_channel_id or self.config.leaderboard_channel_id,
            send_track_channel_id=send_track_channel_id or self.config.send_track_channel_id,
            moderation_role_id=moderation_role_id or self.config.moderation_role_id,
            domme_role_id=domme_role_id or self.config.domme_role_id,
            submissive_role_id=submissive_role_id or self.config.submissive_role_id,
            event_ban_role_id=event_ban_role_id or self.config.event_ban_role_id,
        )
        self.bot.config = self.config
        await interaction.response.send_message(
            view=_simple_view(
                "## ✅ IDs Saved\n\n"
                "Channel and role IDs have been saved to the database and are "
                "active immediately. They will also be loaded on the next restart.",
                colour=GREEN,
            ),
            ephemeral=True,
        )

    # ──────────────────────────────── !event group ────────────────────────────

    @commands.group(name="event", invoke_without_command=True)
    async def event_group(self, ctx: commands.Context[commands.Bot]) -> None:
        await ctx.reply(
            "Available: `!event start`  `!event end`  `!event status`",
            mention_author=False,
        )

    @event_group.command(name="start")
    async def event_start(self, ctx: commands.Context[commands.Bot]) -> None:
        """MOD: open the event start form."""
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.reply("This command only works in a server channel.", mention_author=False)
            return
        if not has_admin_command_permissions(ctx.author, self.config):
            await ctx.reply("You do not have permission to use this command.", mention_author=False)
            return
        await ctx.reply(
            view=EventStartPromptView(self, owner_id=ctx.author.id),
            mention_author=False,
        )

    @event_group.command(name="end")
    async def event_end(self, ctx: commands.Context[commands.Bot]) -> None:
        """MOD: confirm early event end."""
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.reply("This command only works in a server channel.", mention_author=False)
            return
        if not has_admin_command_permissions(ctx.author, self.config):
            await ctx.reply("You do not have permission to use this command.", mention_author=False)
            return
        state = await self.ensure_event_state_current()
        if not state.is_active:
            await ctx.reply("The event is not currently running.", mention_author=False)
            return
        await ctx.reply(
            view=EventEndConfirmView(self, owner_id=ctx.author.id),
            mention_author=False,
        )

    @event_group.command(name="status")
    async def event_status(self, ctx: commands.Context[commands.Bot]) -> None:
        """MOD: show current event state."""
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.reply("This command only works in a server channel.", mention_author=False)
            return
        if not has_admin_command_permissions(ctx.author, self.config):
            await ctx.reply("You do not have permission to use this command.", mention_author=False)
            return
        state = await self.ensure_event_state_current()
        domme_count = len(await self.database.get_all_event_dommes())
        sub_count = await self.database.count_event_ranked_subs()
        domme_totals = await self.database.get_event_domme_totals()
        send_count = sum(r.send_count for r in domme_totals)
        send_total = sum(r.total_usd for r in domme_totals)
        await ctx.reply(
            view=EventStatusView(
                event_name=self.config.event_name,
                state=state,
                domme_count=domme_count,
                sub_count=sub_count,
                send_count=send_count,
                send_total_usd=send_total,
            ),
            mention_author=False,
        )

    # ──────────────────────────────── /register ────────────────────────────────

    @app_commands.command(name="register", description="Register for the event as a Domme or Sub.")
    @app_commands.describe(action="Choose whether you're signing up as a Domme or a Sub.")
    @app_commands.choices(action=[
        app_commands.Choice(name="Domme", value="domme"),
        app_commands.Choice(name="Sub",   value="sub"),
    ])
    async def register(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
    ) -> None:
        signup_type = action.value  # "domme" or "sub"
        reason = await self.get_signup_block_reason(interaction, signup_type=signup_type)
        if reason is not None:
            await interaction.response.send_message(reason, ephemeral=True)
            return
        if signup_type == "domme":
            await interaction.response.send_modal(DommeSignupModal(self))
        else:
            await interaction.response.send_modal(SubSignupModal(self))

    # ──────────────────────────────── sign-up handlers ────────────────────────

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
                "Please enter a valid Throne username or link.", ephemeral=True
            )
            return

        http = await self._get_http()
        creator = await resolve_creator_id(
            normalized,
            http=http,
            timeout_seconds=self.config.throne_http_timeout_seconds,
        )
        if creator is None:
            await interaction.response.send_message(
                "I couldn't find that Throne account. Double-check the username or link and try again.",
                ephemeral=True,
            )
            return

        await self.database.save_event_domme(user_id=interaction.user.id, throne_url=normalized)
        await self.sync_leaderboard_channel()
        await interaction.response.send_message(
            view=_simple_view(
                f"## ✅ You're signed up as a Domme!\n\n"
                f"I'll track sends on: **{normalized}**\n"
                "New sends will appear in the send-track channel and leaderboard automatically.",
                colour=GREEN,
            ),
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
            await interaction.response.send_message("Please enter a name to track.", ephemeral=True)
            return
        if sub_name.casefold() in _RESERVED_SUB_NAMES:
            await interaction.response.send_message("That name is reserved. Pick something else.", ephemeral=True)
            return

        existing = await self.database.get_event_sub_by_name(sub_name=sub_name)
        if existing is not None and existing.user_id != interaction.user.id:
            await interaction.response.send_message(
                "That name is already taken by another sub.", ephemeral=True
            )
            return

        await self.database.save_event_sub(user_id=interaction.user.id, sub_name=sub_name)
        await self.sync_leaderboard_channel()
        await interaction.response.send_message(
            view=_simple_view(
                f"## ✅ You're signed up as a Sub!\n\n"
                f"Tracking name: **{sub_name}**\n"
                "Use that exact name when sending on Throne and I'll credit you on the leaderboard.",
                colour=GREEN,
            ),
            ephemeral=True,
        )

    # ──────────────────────────────── event start/end handlers ────────────────

    async def process_event_start_modal(
        self,
        interaction: discord.Interaction,
        *,
        end_date: str,
        end_time: str,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command only works in the server.", ephemeral=True)
            return
        if not has_admin_command_permissions(interaction.user, self.config):
            await interaction.response.send_message("You do not have permission.", ephemeral=True)
            return

        ends_at = self._parse_end_datetime(end_date=end_date, end_time=end_time)
        if ends_at is None:
            await interaction.response.send_message(
                f"Use `YYYY-MM-DD` for the date and `HH:MM` for the time ({_EVENT_TIMEZONE_LABEL}).",
                ephemeral=True,
            )
            return
        if ends_at <= datetime.now(timezone.utc):
            await interaction.response.send_message("That end time is in the past.", ephemeral=True)
            return

        await self.database.start_event(ends_at=ends_at.isoformat(), started_by=interaction.user.id)
        await self.sync_leaderboard_channel()

        end_label = self._format_discord_timestamp(ends_at)
        await interaction.response.send_message(
            view=_simple_view(
                f"## 🚀 Event Started!\n\n"
                f"**{self.config.event_name}** is now live.\n"
                f"It will end at {end_label}.",
                colour=GREEN,
            ),
            ephemeral=True,
        )

    async def process_event_end(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command only works in the server.", ephemeral=True)
            return
        if not has_admin_command_permissions(interaction.user, self.config):
            await interaction.response.send_message("You do not have permission.", ephemeral=True)
            return

        state = await self.ensure_event_state_current()
        if not state.is_active:
            await interaction.response.edit_message(
                view=_simple_view("The event is not currently running.", colour=BLUE),
            )
            return

        await self.database.end_event(ended_by=interaction.user.id)
        await self.sync_leaderboard_channel()
        await interaction.response.edit_message(
            view=_simple_view(
                f"## 🔴 Event Ended\n\n"
                f"**{self.config.event_name}** has ended.\n"
                "The leaderboards are now frozen.",
                colour=BLUE,
            ),
        )

    # ──────────────────────────────── leaderboard sync ────────────────────────

    async def sync_leaderboard_channel(self) -> None:
        guild = self.bot.get_guild(self.config.guild_id)
        if guild is None:
            return
        state = await self.ensure_event_state_current()
        channel = guild.get_channel(self.config.leaderboard_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        # Sub leaderboard: top 20
        sub_rows_db = await self.database.get_event_sub_totals(limit=20, offset=0)
        sub_rows = [(f"<@{r.user_id}>", r.total_usd, r.send_count) for r in sub_rows_db]
        unclaimed = await self.database.get_event_unclaimed_total()

        # Domme totals: all
        domme_rows_db = await self.database.get_event_domme_totals()
        domme_rows = [(f"<@{r.user_id}>", r.total_usd, r.send_count) for r in domme_rows_db]

        await self._upsert_channel_message(
            message_key="event:sub_leaderboard",
            channel=channel,
            view=SubLeaderboardView(
                event_name=self.config.event_name,
                state=state,
                rows=sub_rows,
                unclaimed_total=unclaimed,
            ),
        )
        await self._upsert_channel_message(
            message_key="event:domme_totals",
            channel=channel,
            view=DommeTotalsView(rows=domme_rows),
        )

    async def _upsert_channel_message(
        self,
        *,
        message_key: str,
        channel: discord.TextChannel,
        view: discord.ui.LayoutView,
    ) -> None:
        existing = await self.database.get_event_message(message_key=message_key)
        message: discord.Message | None = None
        if existing is not None:
            message_id, channel_id = existing
            if channel_id == channel.id:
                try:
                    message = await channel.fetch_message(message_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    message = None

        if message is None:
            message = await channel.send(view=view)
        else:
            await message.edit(view=view)

        await self.database.upsert_event_message(
            message_key=message_key,
            message_id=message.id,
            channel_id=channel.id,
        )
