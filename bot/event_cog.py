from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.config import BotConfig
from bot.database import Database, EventState
from bot.event_embeds import (
    botinfo_embed,
    domme_signup_success_embed,
    domme_totals_embed,
    event_end_confirm_embed,
    event_ended_embed,
    event_start_prompt_embed,
    event_started_embed,
    registration_embed,
    sub_leaderboard_page_embed,
    sub_leaderboard_summary_embed,
    sub_signup_success_embed,
)
from bot.event_views import (
    EventEndConfirmView,
    EventStartPromptView,
    RegistrationPanelView,
    SubLeaderboardView,
)
from bot.throne_scraper import normalize_throne_registration_input, resolve_creator_id
from bot.utils import has_admin_command_permissions

log = logging.getLogger(__name__)

_RESERVED_SUB_NAMES = {"anonymous", "unclaimed send", "unclaimed"}
_EVENT_TIMEZONE = ZoneInfo("Australia/Sydney")
_EVENT_TIMEZONE_LABEL = "Australia/Sydney"


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

    async def restore_runtime(self) -> None:
        self.bot.add_view(RegistrationPanelView(self))

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
        return f"<t:{int(moment.timestamp())}:F> (<t:{int(moment.timestamp())}:R>)"

    def _parse_end_datetime(
        self,
        *,
        end_date: str,
        end_time: str,
    ) -> datetime | None:
        try:
            date_part = datetime.strptime(end_date.strip(), "%Y-%m-%d").date()
            time_part = datetime.strptime(end_time.strip(), "%H:%M").time()
        except ValueError:
            return None
        local_moment = datetime.combine(date_part, time_part, tzinfo=_EVENT_TIMEZONE)
        return local_moment.astimezone(timezone.utc)

    @staticmethod
    def _member_has_role(member: discord.Member, role_id: int) -> bool:
        return role_id > 0 and any(role.id == role_id for role in member.roles)

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

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._synced_on_ready:
            return
        self._synced_on_ready = True
        await self.ensure_event_state_current()
        await self.sync_leaderboard_channel()

    @tasks.loop(minutes=12)
    async def status_loop(self) -> None:
        statuses = [
            self.config.event_name,
            "send totals",
            "pretending this is very organised",
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
            log.warning("Failed to update Rob's status.", exc_info=True)

    @status_loop.before_loop
    async def _before_status_loop(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def event_lifecycle_loop(self) -> None:
        await self.ensure_event_state_current()

    @event_lifecycle_loop.before_loop
    async def _before_event_lifecycle_loop(self) -> None:
        await self.bot.wait_until_ready()

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

    @app_commands.command(
        name="eventpanel",
        description="Post the Mother's Day event registration panel.",
    )
    async def event_panel(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This command only works in the server.",
                ephemeral=True,
            )
            return
        if not has_admin_command_permissions(interaction.user, self.config):
            await interaction.response.send_message(
                "You do not have permission to use this command.",
                ephemeral=True,
            )
            return

        channel = interaction.guild.get_channel(self.config.verification_channel_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "I couldn't find the configured registration channel.",
                ephemeral=True,
            )
            return

        await channel.send(
            embed=registration_embed(
                bot_name=self.config.bot_name,
                event_name=self.config.event_name,
                server_name=interaction.guild.name,
            ),
            view=RegistrationPanelView(self),
        )
        await interaction.response.send_message(
            f"Registration panel posted in {channel.mention}.",
            ephemeral=True,
        )

    @app_commands.command(
        name="leaderboards",
        description="Show the current Mother's Day event leaderboards.",
    )
    async def leaderboards(self, interaction: discord.Interaction) -> None:
        state = await self.ensure_event_state_current()
        summary = await self.build_sub_leaderboard_summary()
        page_embed, total_pages = await self.build_sub_leaderboard_page(0)
        view: SubLeaderboardView | None = None
        if state.is_active or state.ended_at is None:
            view = SubLeaderboardView(self, page=0)
            view.previous_button.disabled = True
            view.next_button.disabled = total_pages <= 1
            view.page_button.label = f"Page 1/{max(total_pages, 1)}"
        domme_embed = await self.build_domme_totals_embed()

        await interaction.response.send_message(embed=summary)
        await interaction.followup.send(embed=page_embed, view=view)
        await interaction.followup.send(embed=domme_embed)

    @app_commands.command(
        name="botinfo",
        description="Show basic info about Rob.",
    )
    async def botinfo(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=botinfo_embed(
                bot_name=self.config.bot_name,
                event_name=self.config.event_name,
                poll_seconds=self.config.throne_poll_interval_seconds,
                server_name=interaction.guild.name if interaction.guild else self.config.bot_name,
            ),
            ephemeral=True,
        )

    @commands.command(name="eventstart")
    async def eventstart(self, ctx: commands.Context[commands.Bot]) -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.reply("This command can only be used in a server channel.", mention_author=False)
            return
        if not has_admin_command_permissions(ctx.author, self.config):
            await ctx.reply("You do not have permission to use this command.", mention_author=False)
            return
        await ctx.reply(
            embed=event_start_prompt_embed(
                event_name=self.config.event_name,
                timezone_name=_EVENT_TIMEZONE_LABEL,
                server_name=ctx.guild.name,
            ),
            view=EventStartPromptView(self, owner_id=ctx.author.id),
            mention_author=False,
        )

    @commands.command(name="eventend")
    async def eventend(self, ctx: commands.Context[commands.Bot]) -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.reply("This command can only be used in a server channel.", mention_author=False)
            return
        if not has_admin_command_permissions(ctx.author, self.config):
            await ctx.reply("You do not have permission to use this command.", mention_author=False)
            return
        state = await self.ensure_event_state_current()
        if not state.is_active:
            await ctx.reply("The event is not currently running.", mention_author=False)
            return
        await ctx.reply(
            embed=event_end_confirm_embed(
                event_name=self.config.event_name,
                server_name=ctx.guild.name,
            ),
            view=EventEndConfirmView(self, owner_id=ctx.author.id),
            mention_author=False,
        )

    async def process_event_start_modal(
        self,
        interaction: discord.Interaction,
        *,
        end_date: str,
        end_time: str,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This command only works in the server.",
                ephemeral=True,
            )
            return
        if not has_admin_command_permissions(interaction.user, self.config):
            await interaction.response.send_message(
                "You do not have permission to use this command.",
                ephemeral=True,
            )
            return

        ends_at = self._parse_end_datetime(end_date=end_date, end_time=end_time)
        if ends_at is None:
            await interaction.response.send_message(
                f"Use `YYYY-MM-DD` for the date and `HH:MM` for the time in {_EVENT_TIMEZONE_LABEL}.",
                ephemeral=True,
            )
            return
        if ends_at <= datetime.now(timezone.utc):
            await interaction.response.send_message(
                "That end time is in the past. Pick a future time.",
                ephemeral=True,
            )
            return

        await self.database.start_event(
            ends_at=ends_at.isoformat(),
            started_by=interaction.user.id,
        )
        await self.sync_leaderboard_channel()
        await interaction.response.send_message(
            embed=event_started_embed(
                event_name=self.config.event_name,
                end_label=self._format_discord_timestamp(ends_at),
                server_name=interaction.guild.name,
            ),
            ephemeral=True,
        )

    async def process_event_end(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This command only works in the server.",
                ephemeral=True,
            )
            return
        if not has_admin_command_permissions(interaction.user, self.config):
            await interaction.response.send_message(
                "You do not have permission to use this command.",
                ephemeral=True,
            )
            return

        state = await self.ensure_event_state_current()
        if not state.is_active:
            await interaction.response.edit_message(
                content="The event is not currently running.",
                embed=None,
                view=None,
            )
            return

        await self.database.end_event(ended_by=interaction.user.id)
        await self.sync_leaderboard_channel()
        await interaction.response.edit_message(
            content=None,
            embed=event_ended_embed(
                event_name=self.config.event_name,
                server_name=interaction.guild.name,
            ),
            view=None,
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
                "Please enter a valid Throne username or Throne link.",
                ephemeral=True,
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

        await self.database.save_event_domme(
            user_id=interaction.user.id,
            throne_url=normalized,
        )
        await self.sync_leaderboard_channel()
        await interaction.response.send_message(
            embed=domme_signup_success_embed(
                throne_url=normalized,
                server_name=interaction.guild.name,
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
            await interaction.response.send_message(
                "Please enter a name to track.",
                ephemeral=True,
            )
            return
        if sub_name.casefold() in _RESERVED_SUB_NAMES:
            await interaction.response.send_message(
                "That name is reserved. Pick something else.",
                ephemeral=True,
            )
            return

        existing = await self.database.get_event_sub_by_name(sub_name=sub_name)
        if existing is not None and existing.user_id != interaction.user.id:
            await interaction.response.send_message(
                "That name is already taken by another sub.",
                ephemeral=True,
            )
            return

        await self.database.save_event_sub(
            user_id=interaction.user.id,
            sub_name=sub_name,
        )
        await self.sync_leaderboard_channel()
        await interaction.response.send_message(
            embed=sub_signup_success_embed(
                sub_name=sub_name,
                server_name=interaction.guild.name,
            ),
            ephemeral=True,
        )

    async def build_sub_leaderboard_summary(self) -> discord.Embed:
        await self.ensure_event_state_current()
        unclaimed_total = await self.database.get_event_unclaimed_total()
        return sub_leaderboard_summary_embed(
            event_name=self.config.event_name,
            unclaimed_total=unclaimed_total,
            server_name=self._server_name(),
        )

    async def build_sub_leaderboard_page(
        self,
        page: int,
    ) -> tuple[discord.Embed, int]:
        state = await self.ensure_event_state_current()
        final_mode = not state.is_active and state.ended_at is not None
        page_size = 5 if final_mode else 10
        if final_mode:
            total_pages = 1
            safe_page = 0
        else:
            total_rows = await self.database.count_event_ranked_subs()
            total_pages = max(1, (total_rows + page_size - 1) // page_size)
            safe_page = min(max(page, 0), total_pages - 1)
        rows = await self.database.get_event_sub_totals(
            limit=page_size,
            offset=safe_page * page_size,
        )
        labels = [(f"<@{row.user_id}>", row) for row in rows]
        return (
            sub_leaderboard_page_embed(
                rows=labels,
                server_name=self._server_name(),
            ),
            total_pages,
        )

    async def build_domme_totals_embed(self) -> discord.Embed:
        await self.ensure_event_state_current()
        rows = await self.database.get_event_domme_totals()
        labels = [(f"<@{row.user_id}>", row) for row in rows]
        return domme_totals_embed(
            event_name=self.config.event_name,
            rows=labels,
            server_name=self._server_name(),
        )

    async def sync_leaderboard_channel(self) -> None:
        guild = self.bot.get_guild(self.config.guild_id)
        if guild is None:
            return
        state = await self.ensure_event_state_current()
        channel = guild.get_channel(self.config.leaderboard_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        summary_embed = await self.build_sub_leaderboard_summary()
        sub_page_embed, total_pages = await self.build_sub_leaderboard_page(0)
        page_view: SubLeaderboardView | None = None
        if state.is_active or state.ended_at is None:
            page_view = SubLeaderboardView(self, page=0)
            page_view.previous_button.disabled = True
            page_view.next_button.disabled = total_pages <= 1
            page_view.page_button.label = f"Page 1/{max(total_pages, 1)}"
        domme_embed = await self.build_domme_totals_embed()

        await self._upsert_channel_message(
            message_key="event:sub_summary",
            channel=channel,
            embed=summary_embed,
        )
        await self._upsert_channel_message(
            message_key="event:sub_page",
            channel=channel,
            embed=sub_page_embed,
            view=page_view,
        )
        await self._upsert_channel_message(
            message_key="event:domme_totals",
            channel=channel,
            embed=domme_embed,
        )

    async def _upsert_channel_message(
        self,
        *,
        message_key: str,
        channel: discord.TextChannel,
        embed: discord.Embed,
        view: discord.ui.View | None = None,
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
            message = await channel.send(embed=embed, view=view)
        else:
            await message.edit(embed=embed, view=view)

        await self.database.upsert_event_message(
            message_key=message_key,
            message_id=message.id,
            channel_id=channel.id,
        )
