from __future__ import annotations

import asyncio
import logging
import random
import re
import sqlite3
import time
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot import embeds, messages
from bot.config import BotConfig
from bot.database import Database, VerificationRequest
from bot.utils import (
    VerificationSubmission,
    display_username,
    extract_verification_submission,
    has_admin_command_permissions,
    has_moderation_role,
    mention_role,
    resolve_message_channel,
    safe_dm,
    user_mention,
)
from bot.views import (
    DommeDeleteConfirmView,
    DommeSetupColorView,
    DommeSetupDetailsView,
    DommeSetupIntroView,
    DommeSetupNameView,
    DommeSetupPaymentsView,
    DommeSetupReviewView,
    DommeSetupThroneView,
    FormLinkView,
    HelpView,
    ReactionRoleSetupModal,
    RoleSelectionView,
    StaffReviewView,
    SubDeleteConfirmView,
    SubSetupColorView,
    SubSetupDetailsView,
    SubSetupIntroView,
    SubSetupKinksLimitsView,
    SubSetupNameView,
    SubSetupOwnerView,
    SubSetupReviewView,
    VerificationPanelView,
)

log = logging.getLogger(__name__)


@dataclass
class DommeProfileSession:
    user_id: int
    message: discord.Message | None = None
    current_view: discord.ui.View | None = None
    name: str | None = None
    honorific: str | None = None
    pronouns: str | None = None
    age: str | None = None
    tribute_price: str | None = None
    throne: str | None = None
    tribute_link: str | None = None
    payment_link1: str | None = None
    payment_link2: str | None = None
    payment_link3: str | None = None
    payment_link4: str | None = None
    content_link1: str | None = None
    content_link2: str | None = None
    content_link3: str | None = None
    content_link4: str | None = None
    profile_color: int = 16737714  # default: pink
    throne_tracking_enabled: bool = False
    kinks: str | None = None
    limits: str | None = None


@dataclass
class SubProfileSession:
    user_id: int
    message: discord.Message | None = None
    current_view: discord.ui.View | None = None
    throne_name: str | None = None
    name: str | None = None
    pronouns: str | None = None
    age: str | None = None
    profile_color: int = 2762042  # default: soft dark
    kinks: str | None = None
    limits: str | None = None
    owned_by_domme_user_id: int | None = None


class ReactionRoleService:
    """Manage reaction-role setup, persistence, and add/remove role events."""

    _CUSTOM_EMOJI_RE = re.compile(r"^<(a?):([a-zA-Z0-9_]{2,32}):(\d+)>$")
    _HEX_COLOR_RE = re.compile(r"^[0-9a-fA-F]{6}$")
    _MAX_REACTION_ROLE_MAPPINGS = 20
    _MAX_UNICODE_EMOJI_LENGTH = 32  # Guardrail against malformed, non-emoji long strings.
    _EMOJI_JOINER_MARKERS = {"\u200d", "\ufe0f", "\u20e3"}

    def __init__(self, bot: commands.Bot, config: BotConfig, database: Database) -> None:
        self.bot = bot
        self.config = config
        self.database = database

    async def create_message_from_modal(
        self,
        *,
        interaction: discord.Interaction,
        channel_id_raw: str,
        title: str,
        description: str,
        color_raw: str,
        mappings_raw: str,
    ) -> None:
        """Validate modal input, post the message, add reactions, and persist mappings."""
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This setup can only be used inside the server.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            channel_id = int(channel_id_raw.strip())
        except ValueError:
            await interaction.followup.send("Channel ID must be a number.", ephemeral=True)
            return

        channel = await resolve_message_channel(self.bot, interaction.guild, channel_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send(
                "The target channel must be a server text channel.",
                ephemeral=True,
            )
            return

        role_mappings = self._parse_role_mappings(mappings_raw, interaction.guild)
        if isinstance(role_mappings, str):
            await interaction.followup.send(role_mappings, ephemeral=True)
            return

        embed_color = self._parse_hex_color(color_raw)
        if embed_color is None:
            await interaction.followup.send(
                "Embed colour must be a valid hex value like #B565FF.",
                ephemeral=True,
            )
            return

        bot_member = interaction.guild.me
        if bot_member is None and self.bot.user is not None:
            bot_member = interaction.guild.get_member(self.bot.user.id)
        if bot_member is None:
            await interaction.followup.send(
                "I couldn't resolve my server member permissions right now.",
                ephemeral=True,
            )
            return
        if not channel.permissions_for(bot_member).send_messages:
            await interaction.followup.send(
                "I don't have permission to send messages in that channel.",
                ephemeral=True,
            )
            return
        if not channel.permissions_for(bot_member).add_reactions:
            await interaction.followup.send(
                "I need Add Reactions permission in that channel.",
                ephemeral=True,
            )
            return
        if not channel.permissions_for(bot_member).manage_roles:
            await interaction.followup.send(
                "I need Manage Roles permission to run reaction roles.",
                ephemeral=True,
            )
            return

        acting_member = interaction.user
        for _emoji_key, emoji_display, role in role_mappings:
            if role >= bot_member.top_role:
                await interaction.followup.send(
                    f"I can't manage {role.mention} because it's above my top role.",
                    ephemeral=True,
                )
                return
            if interaction.guild.owner_id != acting_member.id and role >= acting_member.top_role:
                await interaction.followup.send(
                    f"You can't map {role.mention} because it's above your top role.",
                    ephemeral=True,
                )
                return
            if role.is_default():
                await interaction.followup.send(
                    "You can't use @everyone as a reaction role target.",
                    ephemeral=True,
                )
                return

        embed = embeds.reaction_role_embed(
            title=title.strip(),
            description=description.strip(),
            color=embed_color,
            mappings=[(emoji_display, role.mention) for _k, emoji_display, role in role_mappings],
            creator=interaction.user,
        )

        try:
            message = await channel.send(embed=embed)
        except discord.HTTPException:
            log.exception("Failed to send reaction-role setup message.")
            await interaction.followup.send(
                "I couldn't send the reaction-role message to that channel.",
                ephemeral=True,
            )
            return

        # Ensure all mapped reactions are present on the message.
        successful_mappings: list[tuple[str, str, discord.Role]] = []
        failed_reactions: list[str] = []
        for emoji_key, emoji_display, role in role_mappings:
            try:
                reaction_emoji: str | discord.PartialEmoji
                if emoji_display.startswith("<"):
                    reaction_emoji = discord.PartialEmoji.from_str(emoji_display)
                else:
                    reaction_emoji = emoji_display
                await message.add_reaction(reaction_emoji)
                successful_mappings.append((emoji_key, emoji_display, role))
            except (discord.HTTPException, ValueError):
                failed_reactions.append(emoji_display)
                log.warning(
                    "Failed to add reaction %s to message %s.",
                    emoji_display,
                    message.id,
                )

        if not successful_mappings:
            try:
                await message.delete()
            except discord.HTTPException:
                log.warning("Failed to remove reaction-role message %s after setup failure.", message.id)
            await interaction.followup.send(
                "I couldn't add any of those reactions. No mappings were saved.",
                ephemeral=True,
            )
            return

        for emoji_key, emoji_display, role in successful_mappings:
            await self.database.upsert_reaction_role_binding(
                guild_id=interaction.guild.id,
                channel_id=channel.id,
                message_id=message.id,
                emoji_key=emoji_key,
                emoji_display=emoji_display,
                role_id=role.id,
                created_by=interaction.user.id,
            )

        warning = None
        if failed_reactions:
            failed_list = ", ".join(failed_reactions)
            warning = (
                "Some mappings were skipped because reactions could not be added: "
                f"{failed_list}."
            )
        await interaction.followup.send(
            content=warning,
            embed=embeds.reaction_role_created_embed(message.jump_url, channel, successful_mappings),
            ephemeral=True,
        )

    async def handle_raw_reaction_event(
        self,
        payload: discord.RawReactionActionEvent,
        *,
        added: bool,
    ) -> None:
        """Apply or remove a mapped role when a tracked reaction is added/removed."""
        if payload.guild_id is None:
            return
        if self.bot.user and payload.user_id == self.bot.user.id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        emoji_key = self._emoji_key_from_partial(payload.emoji)
        binding = await self.database.get_reaction_role_binding(
            guild_id=payload.guild_id,
            message_id=payload.message_id,
            emoji_key=emoji_key,
        )
        if binding is None:
            return

        role = guild.get_role(binding.role_id)
        if role is None:
            return

        me = guild.me
        if me is None and self.bot.user is not None:
            me = guild.get_member(self.bot.user.id)
        if me is None or not me.guild_permissions.manage_roles or role >= me.top_role:
            return

        member: discord.Member | None
        if added and payload.member is not None:
            member = payload.member
        else:
            member = guild.get_member(payload.user_id)
            if member is None:
                try:
                    member = await guild.fetch_member(payload.user_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    return
        if member.bot:
            return

        try:
            if added and role not in member.roles:
                await member.add_roles(role, reason="Reaction role added")
            elif not added and role in member.roles:
                await member.remove_roles(role, reason="Reaction role removed")
        except (discord.Forbidden, discord.HTTPException):
            log.warning(
                "Failed to %s reaction role %s for member %s.",
                "add" if added else "remove",
                role.id,
                member.id,
            )

    def _parse_role_mappings(
        self,
        mappings_raw: str,
        guild: discord.Guild,
    ) -> list[tuple[str, str, discord.Role]] | str:
        """Parse `emoji = role` lines into `(emoji_key, emoji_display, role)` tuples."""
        parsed: list[tuple[str, str, discord.Role]] = []
        seen_keys: set[str] = set()

        for raw_line in mappings_raw.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if "=" not in line:
                return f"Invalid mapping `{line}`. Use `emoji = role`."
            emoji_raw, role_raw = (part.strip() for part in line.split("=", 1))
            normalized = self._normalize_emoji(emoji_raw)
            if normalized is None:
                return f"Invalid emoji `{emoji_raw}`."
            emoji_key, emoji_display = normalized

            role_id_str = role_raw
            if role_id_str.startswith("<@&") and role_id_str.endswith(">"):
                role_id_str = role_id_str[3:-1]
            try:
                role_id = int(role_id_str)
            except ValueError:
                return f"Invalid role `{role_raw}`. Use a role mention or role ID."
            role = guild.get_role(role_id)
            if role is None:
                return f"I couldn't find role `{role_raw}` in this server."
            if emoji_key in seen_keys:
                return f"Emoji `{emoji_display}` is duplicated in your mapping."
            seen_keys.add(emoji_key)
            parsed.append((emoji_key, emoji_display, role))

        if not parsed:
            return "Please provide at least one emoji-to-role mapping."
        # Keep this capped for message readability and manageable setup UX.
        if len(parsed) > self._MAX_REACTION_ROLE_MAPPINGS:
            return (
                "Please keep reaction-role mappings to "
                f"{self._MAX_REACTION_ROLE_MAPPINGS} or fewer."
            )
        return parsed

    def _parse_hex_color(self, raw: str) -> discord.Color | None:
        """Parse hex color (with optional #), defaulting to purple when empty."""
        value = raw.strip()
        if not value:
            return embeds.PURPLE
        if value.startswith("#"):
            value = value[1:]
        if not self._HEX_COLOR_RE.fullmatch(value):
            return None
        return discord.Color(int(value, 16))

    def _normalize_emoji(self, raw: str) -> tuple[str, str] | None:
        """Normalize emoji text into `(emoji_key, emoji_display)` for storage/display."""
        value = raw.strip()
        if not value:
            return None
        custom = self._CUSTOM_EMOJI_RE.match(value)
        if custom:
            animated = custom.group(1) == "a"
            emoji_id = custom.group(3)
            emoji_name = custom.group(2)
            display = f"<{'a' if animated else ''}:{emoji_name}:{emoji_id}>"
            return (f"custom:{emoji_id}", display)
        # Guardrail for unusual pasted content; practical upper bound for unicode emoji strings.
        if len(value) > self._MAX_UNICODE_EMOJI_LENGTH:
            return None
        if not self._looks_like_unicode_emoji(value):
            return None
        return (f"unicode:{value}", value)

    def _looks_like_unicode_emoji(self, value: str) -> bool:
        """Best-effort emoji validation to avoid accepting arbitrary plain text."""
        if value.isascii():
            return False
        if any(char.isspace() for char in value):
            return False
        for char in value:
            if (
                char in self._EMOJI_JOINER_MARKERS
                or unicodedata.category(char) in {"So", "Sk"}
                or ord(char) >= 0x1F000
            ):
                return True
        return False

    def _emoji_key_from_partial(self, emoji: discord.PartialEmoji) -> str:
        """Convert a PartialEmoji into the normalized database lookup key."""
        if emoji.id is not None:
            return f"custom:{emoji.id}"
        return f"unicode:{emoji.name or ''}"


class VerificationService:
    def __init__(
        self,
        bot: commands.Bot,
        config: BotConfig,
        database: Database,
    ) -> None:
        self.bot = bot
        self.config = config
        self.database = database
        self.active_sessions: set[tuple[int, int]] = set()
        self.session_tasks: set[asyncio.Task[None]] = set()

    async def restore_persistent_views(self) -> None:
        self.bot.add_view(VerificationPanelView(self))
        pending_requests = await self.database.get_pending_log_requests()
        for request in pending_requests:
            link_url = request.verification_value if request.verification_type == "Link" else None
            self.bot.add_view(StaffReviewView(self, request.id, link_url=link_url))
        log.info("Restored %s pending verification view(s).", len(pending_requests))

    async def handle_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return

        unverified_role = member.guild.get_role(self.config.unverified_role_id)
        if unverified_role:
            try:
                await member.add_roles(unverified_role, reason="The Butler welcome verification")
            except discord.Forbidden:
                log.warning("Missing permission to assign Unverified role to %s.", member.id)
            except discord.HTTPException:
                log.exception("Failed to assign Unverified role to %s.", member.id)
        else:
            log.warning("Configured Unverified role was not found.")

        channel = await resolve_message_channel(self.bot, member.guild, self.config.welcome_channel_id)
        if channel is None:
            return

        try:
            await channel.send(embed=embeds.welcome_embed(member))
        except discord.HTTPException:
            log.exception("Failed to send welcome embed for %s.", member.id)

    async def start_verification(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await self._send_interaction_message(
                interaction,
                "Verification can only be started from the server.",
                ephemeral=True,
            )
            return

        verified_role = interaction.guild.get_role(self.config.verified_role_id)
        if verified_role and verified_role in interaction.user.roles:
            await self._send_interaction_message(
                interaction,
                messages.ALREADY_VERIFIED_RESPONSE,
                ephemeral=True,
            )
            return

        key = (interaction.guild.id, interaction.user.id)
        pending_request = await self.database.get_pending_request(
            user_id=interaction.user.id,
            guild_id=interaction.guild.id,
        )
        if pending_request:
            await self._send_interaction_message(
                interaction,
                messages.DUPLICATE_PENDING_RESPONSE,
                ephemeral=True,
            )
            return

        if key in self.active_sessions:
            await self._send_interaction_message(
                interaction,
                "You already have a verification session in progress. Please check your DMs.",
                ephemeral=True,
            )
            return

        try:
            prompt_message = await interaction.user.send(
                embed=embeds.initial_verification_dm_embed(),
            )
        except (discord.Forbidden, discord.HTTPException):
            await self._send_interaction_message(
                interaction,
                messages.DM_FAILURE_RESPONSE,
                ephemeral=True,
            )
            return

        self.active_sessions.add(key)
        await self._send_interaction_message(
            interaction,
            "I've sent you a DM with verification instructions.",
            ephemeral=True,
        )
        self._start_dm_flow(interaction.user, interaction.guild, key, prompt_message)

    def _start_dm_flow(
        self,
        member: discord.Member,
        guild: discord.Guild,
        key: tuple[int, int],
        prompt_message: discord.Message,
    ) -> None:
        task = asyncio.create_task(self._run_dm_flow_safely(member, guild, key, prompt_message))
        self.session_tasks.add(task)
        task.add_done_callback(self.session_tasks.discard)

    async def _run_dm_flow_safely(
        self,
        member: discord.Member,
        guild: discord.Guild,
        key: tuple[int, int],
        prompt_message: discord.Message,
    ) -> None:
        try:
            await self._run_dm_flow(member, guild, key, prompt_message)
        except Exception:
            log.exception("Unexpected verification session failure for %s.", member.id)
            self.active_sessions.discard(key)
            await self._edit_dm_message(
                prompt_message,
                embed=embeds.session_expired_dm_embed(),
                view=None,
            )

    async def setup_verification_panel(self, ctx: commands.Context[commands.Bot]) -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await self._send_context_message(ctx, "This command can only be used in a server.")
            return

        if not has_admin_command_permissions(ctx.author, self.config):
            await self._send_context_message(ctx, messages.UNAUTHORISED_HELP_RESPONSE)
            return

        channel = await resolve_message_channel(
            self.bot,
            ctx.guild,
            self.config.verification_channel_id,
        )
        if channel is None:
            await self._send_context_message(
                ctx,
                "I couldn't find the configured verification channel.",
            )
            return

        try:
            await channel.send(
                embed=embeds.verification_panel_embed(),
                view=VerificationPanelView(self),
            )
        except discord.HTTPException:
            log.exception("Failed to post verification panel.")
            await self._send_context_message(
                ctx,
                "I couldn't post the verification panel. Please check my channel permissions.",
            )
            return

        await self._send_context_message(
            ctx,
            f"Verification panel posted in {channel.mention}.",
        )

    async def verify_status(
        self,
        ctx: commands.Context[commands.Bot],
        user: discord.User | discord.Member,
    ) -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await self._send_context_message(ctx, "This command can only be used in a server.")
            return

        if not has_admin_command_permissions(ctx.author, self.config):
            await self._send_context_message(ctx, messages.UNAUTHORISED_HELP_RESPONSE)
            return

        request = await self.database.get_latest_request(
            user_id=user.id,
            guild_id=ctx.guild.id,
        )
        await self._send_context_message(
            ctx,
            embed=embeds.verification_status_embed(request, user),
        )

    async def verify_cleanup(self, ctx: commands.Context[commands.Bot]) -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await self._send_context_message(ctx, "This command can only be used in a server.")
            return

        if not has_admin_command_permissions(ctx.author, self.config):
            await self._send_context_message(ctx, messages.UNAUTHORISED_HELP_RESPONSE)
            return

        role = ctx.guild.get_role(self.config.unverified_role_id)
        if role is None:
            await self._send_context_message(ctx, "I couldn't find the configured Unverified role.")
            return

        members = sorted(
            [member for member in role.members if not member.bot],
            key=lambda member: member.display_name.lower(),
        )
        await self._send_context_message(
            ctx,
            embed=embeds.verification_cleanup_embed(role=role, members=members),
        )

    async def review_request(
        self,
        interaction: discord.Interaction,
        request_id: int,
        action: str,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await self._send_interaction_message(
                interaction,
                messages.UNAUTHORISED_STAFF_BUTTON_RESPONSE,
                ephemeral=True,
            )
            return

        if not has_moderation_role(interaction.user, self.config):
            await self._send_interaction_message(
                interaction,
                messages.UNAUTHORISED_STAFF_BUTTON_RESPONSE,
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        claimed = await self.database.claim_pending_request(
            request_id=request_id,
            reviewed_by=interaction.user.id,
        )
        if not claimed:
            await interaction.followup.send(
                "This verification request is already being reviewed by another moderator or has already been processed.",
                ephemeral=True,
            )
            return

        request = await self.database.get_request(request_id)
        if request is None or request.status != "pending":
            await self.database.release_request_claim(
                request_id=request_id,
                reviewed_by=interaction.user.id,
            )
            await interaction.followup.send(
                "This verification request has already been processed.",
                ephemeral=True,
            )
            return

        if action == "approve":
            await self._approve_request(interaction, request)
        elif action == "deny_underage":
            await self._deny_request(
                interaction,
                request,
                status="denied_underage",
                dm_embed=embeds.denied_underage_dm_embed(),
                log_title="Verification Denied - Under 18",
                log_color=embeds.RED,
                log_status="Denied - Under 18",
                followup="Verification denied as under 18.",
            )
        elif action == "deny_invalid":
            await self._deny_request(
                interaction,
                request,
                status="denied_invalid",
                dm_embed=embeds.denied_invalid_dm_embed(),
                log_title="Verification Denied - Invalid Service",
                log_color=embeds.ORANGE,
                log_status="Denied - Invalid Service",
                followup="Verification denied for invalid service.",
            )
        else:
            await self.database.release_request_claim(
                request_id=request_id,
                reviewed_by=interaction.user.id,
            )
            await interaction.followup.send("Unknown verification action.", ephemeral=True)

    async def _run_dm_flow(
        self,
        member: discord.Member,
        guild: discord.Guild,
        key: tuple[int, int],
        prompt_message: discord.Message,
    ) -> None:
        try:
            submission = await self._wait_for_submission(member, prompt_message)
            if submission is None:
                await self._edit_dm_message(
                    prompt_message,
                    embed=embeds.session_expired_dm_embed(),
                    view=None,
                )
                await self._record_expired(member, guild)
                return

            selected_role = await self._ask_role(member, prompt_message)
            if selected_role is None:
                await self._edit_dm_message(
                    prompt_message,
                    embed=embeds.session_expired_dm_embed(),
                    view=None,
                )
                await self._record_expired(member, guild, submission=submission)
                return

            try:
                request_id = await self.database.create_request(
                    user_id=member.id,
                    guild_id=guild.id,
                    username=display_username(member),
                    verification_type=submission.verification_type,
                    verification_value=submission.verification_value,
                    selected_role=selected_role,
                )
            except sqlite3.IntegrityError:
                await safe_dm(member, content=messages.DUPLICATE_PENDING_RESPONSE)
                return

            request = await self.database.get_request(request_id)
            if request is None:
                log.error("Created verification request %s but could not fetch it.", request_id)
                await self._edit_dm_message(
                    prompt_message,
                    embed=embeds.session_expired_dm_embed(),
                    view=None,
                )
                return

            submitted = await self._submit_to_staff(guild, member, request)
            if not submitted:
                await self.database.mark_reviewed(
                    request_id=request.id,
                    status="expired",
                    reviewed_by=None,
                )
                await self._edit_dm_message(
                    prompt_message,
                    embed=embeds.session_expired_dm_embed(),
                    view=None,
                )
                return

            await safe_dm(
                member,
                embed=embeds.pending_review_embed(),
                view=FormLinkView(),
            )
        finally:
            self.active_sessions.discard(key)

    async def _wait_for_submission(
        self,
        member: discord.Member,
        prompt_message: discord.Message,
    ) -> VerificationSubmission | None:
        deadline = time.monotonic() + 300

        def check(message: discord.Message) -> bool:
            return message.author.id == member.id and message.guild is None

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None

            try:
                message = await self.bot.wait_for("message", check=check, timeout=remaining)
            except asyncio.TimeoutError:
                return None

            submission = extract_verification_submission(message)
            if submission:
                return submission

            await self._edit_dm_message(
                prompt_message,
                embed=embeds.initial_verification_dm_embed(messages.INVALID_SUBMISSION_DM_DESCRIPTION),
                view=None,
            )

    async def _ask_role(
        self,
        member: discord.Member,
        prompt_message: discord.Message,
    ) -> str | None:
        view = RoleSelectionView(member.id)
        view.message = prompt_message
        await self._edit_dm_message(
            prompt_message,
            embed=embeds.role_prompt_embed(),
            view=view,
        )

        timed_out = await view.wait()
        if timed_out:
            return None

        await self._edit_dm_message(
            prompt_message,
            embed=embeds.role_prompt_embed(view.selection),
            view=view,
        )
        return view.selection

    async def _submit_to_staff(
        self,
        guild: discord.Guild,
        member: discord.Member,
        request: VerificationRequest,
    ) -> bool:
        channel = await resolve_message_channel(self.bot, guild, self.config.verify_log_channel_id)
        if channel is None:
            return False

        link_url = request.verification_value if request.verification_type == "Link" else None
        view = StaffReviewView(self, request.id, link_url=link_url)
        try:
            message = await channel.send(
                content=mention_role(self.config.moderation_role_id),
                embed=embeds.verification_log_embed(request, member),
                view=view,
                allowed_mentions=discord.AllowedMentions(roles=True),
            )
        except discord.HTTPException:
            log.exception("Failed to send verification request %s to staff.", request.id)
            return False

        await self.database.set_log_message(
            request_id=request.id,
            log_message_id=message.id,
            log_channel_id=message.channel.id,
        )
        return True

    async def _approve_request(
        self,
        interaction: discord.Interaction,
        request: VerificationRequest,
    ) -> None:
        assert interaction.guild is not None
        assert isinstance(interaction.user, discord.Member)

        member = await self._get_member(interaction.guild, request.user_id)
        if member is None:
            await self.database.release_request_claim(
                request_id=request.id,
                reviewed_by=interaction.user.id,
            )
            await interaction.followup.send(
                "I couldn't find that user in the server, so roles were not changed.",
                ephemeral=True,
            )
            return

        verified_role = interaction.guild.get_role(self.config.verified_role_id)
        selected_role_id = (
            self.config.domme_role_id
            if request.selected_role == "Domme"
            else self.config.submissive_role_id
        )
        selected_role = interaction.guild.get_role(selected_role_id)
        unverified_role = interaction.guild.get_role(self.config.unverified_role_id)

        missing_roles = []
        if verified_role is None:
            missing_roles.append("Verified")
        if selected_role is None:
            missing_roles.append(request.selected_role or "Selected")
        if missing_roles:
            await self.database.release_request_claim(
                request_id=request.id,
                reviewed_by=interaction.user.id,
            )
            await interaction.followup.send(
                f"I couldn't find the configured role(s): {', '.join(missing_roles)}.",
                ephemeral=True,
            )
            return

        try:
            if unverified_role and unverified_role in member.roles:
                await member.remove_roles(
                    unverified_role,
                    reason=f"Approved by {interaction.user}",
                )

            roles_to_add = [
                role
                for role in (verified_role, selected_role)
                if role is not None and role not in member.roles
            ]
            if roles_to_add:
                await member.add_roles(
                    *roles_to_add,
                    reason=f"Approved by {interaction.user}",
                )
        except discord.Forbidden:
            await self.database.release_request_claim(
                request_id=request.id,
                reviewed_by=interaction.user.id,
            )
            await interaction.followup.send(
                "I don't have permission to update that user's roles.",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            log.exception("Failed to update roles for %s.", member.id)
            await self.database.release_request_claim(
                request_id=request.id,
                reviewed_by=interaction.user.id,
            )
            await interaction.followup.send(
                "Discord rejected the role update. Please try again.",
                ephemeral=True,
            )
            return

        updated = await self.database.mark_reviewed(
            request_id=request.id,
            status="approved",
            reviewed_by=interaction.user.id,
        )
        if not updated:
            await self.database.release_request_claim(
                request_id=request.id,
                reviewed_by=interaction.user.id,
            )
            await interaction.followup.send(
                "This verification request has already been processed.",
                ephemeral=True,
            )
            return

        await safe_dm(member, embed=embeds.approved_dm_embed(self.config))
        await self._send_general_announcement(request)
        await self._edit_staff_message(
            interaction,
            request,
            title="User Verified!",
            color=embeds.GREEN,
            status="Approved",
        )
        await interaction.followup.send("Verification approved.", ephemeral=True)

    async def _deny_request(
        self,
        interaction: discord.Interaction,
        request: VerificationRequest,
        *,
        status: str,
        dm_embed: discord.Embed,
        log_title: str,
        log_color: discord.Color,
        log_status: str,
        followup: str,
    ) -> None:
        assert isinstance(interaction.user, discord.Member)

        updated = await self.database.mark_reviewed(
            request_id=request.id,
            status=status,
            reviewed_by=interaction.user.id,
        )
        if not updated:
            await self.database.release_request_claim(
                request_id=request.id,
                reviewed_by=interaction.user.id,
            )
            await interaction.followup.send(
                "This verification request has already been processed.",
                ephemeral=True,
            )
            return

        user = self.bot.get_user(request.user_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(request.user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                user = None

        if user:
            await safe_dm(user, embed=dm_embed)

        await self._edit_staff_message(
            interaction,
            request,
            title=log_title,
            color=log_color,
            status=log_status,
        )
        await interaction.followup.send(followup, ephemeral=True)

    async def _edit_staff_message(
        self,
        interaction: discord.Interaction,
        request: VerificationRequest,
        *,
        title: str,
        color: discord.Color,
        status: str,
    ) -> None:
        assert isinstance(interaction.user, discord.Member)
        link_url = request.verification_value if request.verification_type == "Link" else None
        view = StaffReviewView(None, request.id, link_url=link_url, disabled=True)
        embed = embeds.verification_outcome_embed(
            request=request,
            moderator=interaction.user,
            title=title,
            color=color,
            status=status,
        )
        try:
            if interaction.message:
                await interaction.message.edit(content=None, embed=embed, view=view)
        except discord.HTTPException:
            log.exception("Failed to edit staff verification message %s.", request.id)

    async def _send_general_announcement(self, request: VerificationRequest) -> None:
        guild = self.bot.get_guild(request.guild_id)
        if guild is None:
            return

        channel = await resolve_message_channel(self.bot, guild, self.config.general_channel_id)
        if channel is None:
            return

        template = random.choice(
            messages.GENERAL_DOMME_MESSAGES
            if request.selected_role == "Domme"
            else messages.GENERAL_SUBMISSIVE_MESSAGES
        )
        try:
            await channel.send(template.format(user_mention=user_mention(request.user_id)))
        except discord.HTTPException:
            log.exception("Failed to send general announcement for %s.", request.user_id)

    async def _record_expired(
        self,
        member: discord.Member,
        guild: discord.Guild,
        *,
        submission: VerificationSubmission | None = None,
    ) -> None:
        try:
            await self.database.create_request(
                user_id=member.id,
                guild_id=guild.id,
                username=display_username(member),
                verification_type=submission.verification_type if submission else None,
                verification_value=submission.verification_value if submission else None,
                selected_role=None,
                status="expired",
            )
        except sqlite3.IntegrityError:
            pass

    async def _edit_dm_message(
        self,
        message: discord.Message,
        *,
        embed: discord.Embed,
        view: discord.ui.View | None,
    ) -> None:
        try:
            await message.edit(embed=embed, view=view)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            log.exception("Failed to edit DM message %s.", message.id)

    async def _get_member(
        self,
        guild: discord.Guild,
        user_id: int,
    ) -> discord.Member | None:
        member = guild.get_member(user_id)
        if member:
            return member
        try:
            return await guild.fetch_member(user_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    async def _send_context_message(
        self,
        ctx: commands.Context[commands.Bot],
        content: str | None = None,
        *,
        embed: discord.Embed | None = None,
    ) -> None:
        await ctx.reply(content=content, embed=embed, mention_author=False)

    async def _send_interaction_message(
        self,
        interaction: discord.Interaction,
        content: str | None = None,
        *,
        embed: discord.Embed | None = None,
        ephemeral: bool = False,
    ) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(content=content, embed=embed, ephemeral=ephemeral)


class DommeProfileService:
    def __init__(
        self,
        bot: commands.Bot,
        config: BotConfig,
        database: Database,
    ) -> None:
        self.bot = bot
        self.config = config
        self.database = database
        self.sessions: dict[int, DommeProfileSession] = {}

    def finish_session(self, user_id: int) -> None:
        self.sessions.pop(user_id, None)

    def build_later_embed(self) -> discord.Embed:
        return embeds.domme_setup_later_embed()

    def build_cancelled_embed(self) -> discord.Embed:
        return embeds.domme_setup_cancelled_embed()

    def _make_session_from_profile(self, profile: "DommeProfile") -> DommeProfileSession:
        """Pre-populate a session from an existing saved profile."""
        from bot.database import DommeProfile
        session = DommeProfileSession(user_id=profile.user_id)
        session.name = profile.name
        session.honorific = profile.honorific
        session.pronouns = profile.pronouns
        session.age = profile.age
        session.tribute_price = profile.tribute_price
        session.throne = profile.throne
        session.tribute_link = profile.tribute_link
        session.payment_link1 = profile.payment_link1
        session.payment_link2 = profile.payment_link2
        session.payment_link3 = profile.payment_link3
        session.payment_link4 = profile.payment_link4
        session.content_link1 = profile.content_link1
        session.content_link2 = profile.content_link2
        session.content_link3 = profile.content_link3
        session.content_link4 = profile.content_link4
        session.profile_color = profile.profile_color
        session.throne_tracking_enabled = profile.throne_tracking_enabled
        session.kinks = profile.kinks
        session.limits = profile.limits
        return session

    async def start_setup(self, member: discord.Member) -> bool:
        """Start setup via DM (server-triggered flow)."""
        existing = await self.database.get_domme_profile(user_id=member.id)
        session = (
            self._make_session_from_profile(existing)
            if existing
            else DommeProfileSession(user_id=member.id)
        )
        view = DommeSetupIntroView(self, session)
        try:
            session.message = await member.send(
                embed=embeds.domme_setup_intro_embed(),
                view=view,
            )
        except (discord.Forbidden, discord.HTTPException):
            return False
        session.current_view = view
        self.sessions[member.id] = session
        return True

    async def start_setup_in_dm(
        self,
        user: discord.User,
        interaction: discord.Interaction,
    ) -> None:
        """Start (or resume) setup when the user runs /domme inside a DM."""
        existing = await self.database.get_domme_profile(user_id=user.id)
        session = (
            self._make_session_from_profile(existing)
            if existing
            else DommeProfileSession(user_id=user.id)
        )
        view = DommeSetupIntroView(self, session)
        await interaction.response.send_message(
            embed=embeds.domme_setup_intro_embed(),
            view=view,
        )
        session.message = await interaction.original_response()
        session.current_view = view
        self.sessions[user.id] = session

    async def show_intro_step(
        self,
        session: DommeProfileSession,
        interaction: discord.Interaction,
    ) -> None:
        await self._update_session_message(
            session,
            interaction=interaction,
            embed=embeds.domme_setup_intro_embed(),
            view=DommeSetupIntroView(self, session),
        )

    async def show_name_step(
        self,
        session: DommeProfileSession,
        interaction: discord.Interaction,
    ) -> None:
        await self._update_session_message(
            session,
            interaction=interaction,
            embed=embeds.domme_setup_name_embed(
                name=session.name,
                honorific=session.honorific,
            ),
            view=DommeSetupNameView(self, session),
        )

    async def show_details_step(
        self,
        session: DommeProfileSession,
        interaction: discord.Interaction,
    ) -> None:
        await self._update_session_message(
            session,
            interaction=interaction,
            embed=embeds.domme_setup_details_embed(
                pronouns=session.pronouns,
                age=session.age,
                tribute_price=session.tribute_price,
                kinks=session.kinks,
                limits=session.limits,
            ),
            view=DommeSetupDetailsView(self, session),
        )

    async def show_payments_step(
        self,
        session: DommeProfileSession,
        interaction: discord.Interaction,
    ) -> None:
        await self._update_session_message(
            session,
            interaction=interaction,
            embed=embeds.domme_setup_links_embed(
                throne=session.throne,
                tribute_link=session.tribute_link,
                payment_link1=session.payment_link1,
                payment_link2=session.payment_link2,
                payment_link3=session.payment_link3,
                payment_link4=session.payment_link4,
                content_link1=session.content_link1,
                content_link2=session.content_link2,
                content_link3=session.content_link3,
                content_link4=session.content_link4,
            ),
            view=DommeSetupPaymentsView(self, session),
        )

    async def refresh_payments_step(
        self,
        session: DommeProfileSession,
        interaction: discord.Interaction,
    ) -> None:
        await self.show_payments_step(session, interaction)

    async def advance_after_payments(
        self,
        session: DommeProfileSession,
        interaction: discord.Interaction,
    ) -> None:
        if session.throne:
            await self.show_throne_step(session, interaction)
            return
        session.throne_tracking_enabled = False
        await self.show_color_step(session, interaction)

    async def show_throne_step(
        self,
        session: DommeProfileSession,
        interaction: discord.Interaction,
    ) -> None:
        await self._update_session_message(
            session,
            interaction=interaction,
            embed=embeds.domme_setup_throne_embed(throne=session.throne),
            view=DommeSetupThroneView(self, session),
        )

    async def show_color_step(
        self,
        session: DommeProfileSession,
        interaction: discord.Interaction,
    ) -> None:
        await self._update_session_message(
            session,
            interaction=interaction,
            embed=embeds.domme_setup_color_embed(profile_color=session.profile_color),
            view=DommeSetupColorView(self, session),
        )

    async def show_review_step(
        self,
        session: DommeProfileSession,
        interaction: discord.Interaction,
    ) -> None:
        await self._update_session_message(
            session,
            interaction=interaction,
            embed=embeds.domme_setup_review_embed(
                name=session.name,
                honorific=session.honorific,
                pronouns=session.pronouns,
                age=session.age,
                tribute_price=session.tribute_price,
                throne=session.throne,
                tribute_link=session.tribute_link,
                payment_link1=session.payment_link1,
                payment_link2=session.payment_link2,
                payment_link3=session.payment_link3,
                payment_link4=session.payment_link4,
                content_link1=session.content_link1,
                content_link2=session.content_link2,
                content_link3=session.content_link3,
                content_link4=session.content_link4,
                profile_color=session.profile_color,
                throne_tracking_enabled=session.throne_tracking_enabled,
                kinks=session.kinks,
                limits=session.limits,
            ),
            view=DommeSetupReviewView(self, session),
        )

    async def save_profile(
        self,
        session: DommeProfileSession,
        interaction: discord.Interaction,
    ) -> None:
        await self.database.save_domme_profile(
            user_id=session.user_id,
            name=session.name,
            honorific=session.honorific,
            pronouns=session.pronouns,
            age=session.age,
            tribute_price=session.tribute_price,
            throne=session.throne,
            tribute_link=session.tribute_link,
            payment_link1=session.payment_link1,
            payment_link2=session.payment_link2,
            payment_link3=session.payment_link3,
            payment_link4=session.payment_link4,
            content_link1=session.content_link1,
            content_link2=session.content_link2,
            content_link3=session.content_link3,
            content_link4=session.content_link4,
            profile_color=session.profile_color,
            throne_tracking_enabled=session.throne_tracking_enabled,
            kinks=session.kinks,
            limits=session.limits,
        )
        self.finish_session(session.user_id)
        await self._update_session_message(
            session,
            interaction=interaction,
            embed=embeds.domme_setup_complete_embed(),
            view=None,
        )

    async def delete_profile(self, interaction: discord.Interaction, user_id: int) -> None:
        deleted = await self.database.delete_domme_profile(user_id=user_id)
        if deleted:
            await interaction.response.edit_message(
                content="Your Domme profile has been deleted.",
                view=None,
            )
            return
        await interaction.response.edit_message(
            content="I couldn't find a saved Domme profile to delete.",
            view=None,
        )

    async def _update_session_message(
        self,
        session: DommeProfileSession,
        *,
        interaction: discord.Interaction,
        embed: discord.Embed,
        view: discord.ui.View | None,
    ) -> None:
        if session.message is None:
            return

        previous_view = session.current_view
        if previous_view and previous_view is not view:
            previous_view.stop()

        try:
            if interaction.response.is_done():
                await session.message.edit(embed=embed, view=view)
            else:
                await interaction.response.edit_message(embed=embed, view=view)
                if interaction.message:
                    session.message = interaction.message
            session.current_view = view
        except discord.HTTPException:
            log.exception("Failed to update Domme profile setup for %s.", session.user_id)
            self.finish_session(session.user_id)


def _normalize_url(url: str) -> str | None:
    """Ensure a URL has a scheme (prepend https:// if missing) and is http/https.

    Returns the normalized URL, or None if the URL is empty or uses an
    unsupported scheme.
    """
    url = url.strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme:
        # Already has a scheme — accept http/https only
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return None
        return url
    # No scheme detected — prepend https://
    url = "https://" + url
    parsed = urlparse(url)
    if not parsed.netloc:
        return None
    return url


def _tribute_view(profile: "DommeProfile") -> discord.ui.View | None:
    """Return a View with a Tribute link button, or None if no valid tribute_link."""
    from bot.database import DommeProfile
    if not profile.tribute_link:
        return None
    safe_url = _normalize_url(profile.tribute_link)
    if safe_url is None:
        return None

    class TributeView(discord.ui.View):
        def __init__(self) -> None:
            super().__init__(timeout=None)
            self.add_item(
                discord.ui.Button(
                    label="💸 Tribute",
                    url=safe_url,
                    style=discord.ButtonStyle.link,
                )
            )

    return TributeView()


class SubProfileService:
    def __init__(
        self,
        bot: discord.Client,
        config: BotConfig,
        database: Database,
    ) -> None:
        self.bot = bot
        self.config = config
        self.database = database
        self.sessions: dict[int, SubProfileSession] = {}

    def finish_session(self, user_id: int) -> None:
        self.sessions.pop(user_id, None)

    def build_later_embed(self) -> discord.Embed:
        return embeds.sub_setup_later_embed()

    def build_cancelled_embed(self) -> discord.Embed:
        return embeds.sub_setup_cancelled_embed()

    def _make_session_from_profile(self, profile: "SubProfile") -> SubProfileSession:
        """Pre-populate a session from an existing saved sub profile."""
        from bot.database import SubProfile
        session = SubProfileSession(user_id=profile.user_id)
        session.throne_name = profile.throne_name
        session.name = profile.name
        session.pronouns = profile.pronouns
        session.age = profile.age
        session.profile_color = profile.profile_color
        session.kinks = profile.kinks
        session.limits = profile.limits
        session.owned_by_domme_user_id = profile.owned_by_domme_user_id
        return session

    async def start_setup_via_server(self, member: discord.Member) -> bool:
        """Start setup by sending a DM (server-triggered flow)."""
        existing = await self.database.get_sub_profile(user_id=member.id)
        session = (
            self._make_session_from_profile(existing)
            if existing
            else SubProfileSession(user_id=member.id)
        )
        view = SubSetupIntroView(self, session)
        try:
            session.message = await member.send(
                embed=embeds.sub_setup_intro_embed(),
                view=view,
            )
        except (discord.Forbidden, discord.HTTPException):
            return False
        session.current_view = view
        self.sessions[member.id] = session
        return True

    async def start_setup_in_dm(
        self,
        user: discord.User,
        interaction: discord.Interaction,
    ) -> None:
        """Start (or resume) setup when the user runs /sub inside a DM."""
        existing = await self.database.get_sub_profile(user_id=user.id)
        session = (
            self._make_session_from_profile(existing)
            if existing
            else SubProfileSession(user_id=user.id)
        )
        view = SubSetupIntroView(self, session)
        await interaction.response.send_message(
            embed=embeds.sub_setup_intro_embed(),
            view=view,
        )
        session.message = await interaction.original_response()
        session.current_view = view
        self.sessions[user.id] = session

    async def show_intro_step(
        self,
        session: SubProfileSession,
        interaction: discord.Interaction,
    ) -> None:
        await self._update_session_message(
            session,
            interaction=interaction,
            embed=embeds.sub_setup_intro_embed(),
            view=SubSetupIntroView(self, session),
        )

    async def show_name_step(
        self,
        session: SubProfileSession,
        interaction: discord.Interaction,
    ) -> None:
        await self._update_session_message(
            session,
            interaction=interaction,
            embed=embeds.sub_setup_name_embed(throne_name=session.throne_name),
            view=SubSetupNameView(self, session),
        )

    async def show_details_step(
        self,
        session: SubProfileSession,
        interaction: discord.Interaction,
    ) -> None:
        await self._update_session_message(
            session,
            interaction=interaction,
            embed=embeds.sub_setup_details_embed(
                name=session.name,
                pronouns=session.pronouns,
                age=session.age,
            ),
            view=SubSetupDetailsView(self, session),
        )

    async def show_kinks_limits_step(
        self,
        session: SubProfileSession,
        interaction: discord.Interaction,
    ) -> None:
        await self._update_session_message(
            session,
            interaction=interaction,
            embed=embeds.sub_setup_kinks_limits_embed(
                kinks=session.kinks,
                limits=session.limits,
            ),
            view=SubSetupKinksLimitsView(self, session),
        )

    async def show_color_step(
        self,
        session: SubProfileSession,
        interaction: discord.Interaction,
    ) -> None:
        await self._update_session_message(
            session,
            interaction=interaction,
            embed=embeds.sub_setup_color_embed(profile_color=session.profile_color),
            view=SubSetupColorView(self, session),
        )

    async def show_owner_step(
        self,
        session: SubProfileSession,
        interaction: discord.Interaction,
    ) -> None:
        options = await self._build_owner_options(session)
        await self._update_session_message(
            session,
            interaction=interaction,
            embed=embeds.sub_setup_owner_embed(
                owned_by_label=self._owner_label(session),
            ),
            view=SubSetupOwnerView(self, session, options),
        )

    async def refresh_owner_step(
        self,
        session: SubProfileSession,
        interaction: discord.Interaction,
        options: list[discord.SelectOption],
    ) -> None:
        await self._update_session_message(
            session,
            interaction=interaction,
            embed=embeds.sub_setup_owner_embed(
                owned_by_label=self._owner_label(session),
            ),
            view=SubSetupOwnerView(self, session, options),
        )

    def _owner_label(self, session: SubProfileSession) -> str:
        if session.owned_by_domme_user_id:
            guild = self.bot.get_guild(self.config.guild_id)
            if guild:
                member = guild.get_member(session.owned_by_domme_user_id)
                if member:
                    return member.display_name
            return f"<@{session.owned_by_domme_user_id}>"
        return "None"

    async def _build_owner_options(self, session: SubProfileSession) -> list[discord.SelectOption]:
        options: list[discord.SelectOption] = [
            discord.SelectOption(label="None — I'm not owned", value="none"),
        ]
        guild = self.bot.get_guild(self.config.guild_id)
        domme_profiles = await self.database.get_all_domme_profiles()
        for profile in domme_profiles[:24]:  # Discord max 25 options (1 reserved for None)
            member = guild.get_member(profile.user_id) if guild else None
            display = member.display_name if member else f"User {profile.user_id}"
            if profile.name:
                display = f"{profile.name} ({display})"
            options.append(
                discord.SelectOption(
                    label=display[:100],
                    value=str(profile.user_id),
                    default=(session.owned_by_domme_user_id == profile.user_id),
                )
            )
        return options

    async def show_review_step(
        self,
        session: SubProfileSession,
        interaction: discord.Interaction,
    ) -> None:
        owned_by_label = self._owner_label(session)
        await self._update_session_message(
            session,
            interaction=interaction,
            embed=embeds.sub_setup_review_embed(
                throne_name=session.throne_name,
                name=session.name,
                pronouns=session.pronouns,
                age=session.age,
                profile_color=session.profile_color,
                kinks=session.kinks,
                limits=session.limits,
                owned_by_label=owned_by_label,
            ),
            view=SubSetupReviewView(self, session),
        )

    async def save_profile(
        self,
        session: SubProfileSession,
        interaction: discord.Interaction,
    ) -> None:
        await self.database.save_sub_profile(
            user_id=session.user_id,
            throne_name=session.throne_name,
            name=session.name,
            pronouns=session.pronouns,
            age=session.age,
            profile_color=session.profile_color,
            kinks=session.kinks,
            limits=session.limits,
            owned_by_domme_user_id=session.owned_by_domme_user_id,
        )
        self.finish_session(session.user_id)
        await self._update_session_message(
            session,
            interaction=interaction,
            embed=embeds.sub_setup_complete_embed(),
            view=None,
        )

    async def delete_profile(self, interaction: discord.Interaction, user_id: int) -> None:
        deleted = await self.database.delete_sub_profile(user_id=user_id)
        if deleted:
            await interaction.response.edit_message(
                content="Your sub profile has been deleted.",
                view=None,
            )
            return
        await interaction.response.edit_message(
            content="I couldn't find a saved sub profile to delete.",
            view=None,
        )

    async def _update_session_message(
        self,
        session: SubProfileSession,
        *,
        interaction: discord.Interaction,
        embed: discord.Embed,
        view: discord.ui.View | None,
    ) -> None:
        if session.message is None:
            return
        previous_view = session.current_view
        if previous_view and previous_view is not view:
            previous_view.stop()
        try:
            if interaction.response.is_done():
                await session.message.edit(embed=embed, view=view)
            else:
                await interaction.response.edit_message(embed=embed, view=view)
                if interaction.message:
                    session.message = interaction.message
            session.current_view = view
        except discord.HTTPException:
            log.exception("Failed to update sub profile setup for %s.", session.user_id)
            self.finish_session(session.user_id)


class VerificationCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        config: BotConfig,
        database: Database,
    ) -> None:
        self.bot = bot
        self.config = config
        self.database = database
        self.service = VerificationService(bot, config, database)
        self.domme_service = DommeProfileService(bot, config, database)
        self.sub_service = SubProfileService(bot, config, database)
        self.reaction_role_service = ReactionRoleService(bot, config, database)
        self.leaderboard_task.start()

    def cog_unload(self) -> None:
        self.leaderboard_task.cancel()

    @tasks.loop(minutes=5)
    async def leaderboard_task(self) -> None:
        """Update the server leaderboard message every 5 minutes."""
        if not self.config.leaderboard_channel_id:
            return
        guild = self.bot.get_guild(self.config.guild_id)
        if guild is None:
            return
        channel = guild.get_channel(self.config.leaderboard_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        rows = await self.database.get_leaderboard_top_sends()
        embed = embeds.server_leaderboard_embed(rows, self.bot)
        stored = await self.database.get_leaderboard_message(guild_id=guild.id)
        if stored is not None:
            msg_id, _ = stored
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(embed=embed)
                return
            except discord.NotFound:
                pass
        # Post a new leaderboard message and pin it
        try:
            msg = await channel.send(embed=embed)
            await self.database.upsert_leaderboard_message(
                guild_id=guild.id,
                message_id=msg.id,
                channel_id=channel.id,
            )
            try:
                await msg.pin()
            except (discord.Forbidden, discord.HTTPException):
                log.warning("Could not pin leaderboard message in channel %s.", channel.id)
        except discord.HTTPException:
            log.exception("Failed to post leaderboard message.")

    @leaderboard_task.before_loop
    async def before_leaderboard_task(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await self.service.handle_member_join(member)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        await self.reaction_role_service.handle_raw_reaction_event(payload, added=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        await self.reaction_role_service.handle_raw_reaction_event(payload, added=False)

    @commands.command(name="setup_verification")
    async def setup_verification(self, ctx: commands.Context[commands.Bot]) -> None:
        await self.service.setup_verification_panel(ctx)

    @commands.command(name="verify_status")
    async def verify_status(
        self,
        ctx: commands.Context[commands.Bot],
        user: discord.User,
    ) -> None:
        await self.service.verify_status(ctx, user)

    @commands.command(name="verify_cleanup")
    async def verify_cleanup(self, ctx: commands.Context[commands.Bot]) -> None:
        await self.service.verify_cleanup(ctx)

    @commands.command(name="resync")
    async def resync(self, ctx: commands.Context[commands.Bot], mode: str | None = None) -> None:
        """Admin/dev command to sync app commands (`guild`, `clear`, or `global`)."""
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.reply("This command can only be used in a server.", mention_author=False)
            return
        if not has_admin_command_permissions(ctx.author, self.config):
            await ctx.reply(messages.UNAUTHORISED_HELP_RESPONSE, mention_author=False)
            return

        mode_value = (mode or "guild").strip().lower()
        guild_obj = discord.Object(id=self.config.guild_id)
        valid_modes = {"guild", "clear", "global"}
        if mode_value not in valid_modes:
            await ctx.reply(
                "Invalid mode. Use `!resync guild`, `!resync clear`, or `!resync global`.",
                mention_author=False,
            )
            return

        try:
            if mode_value == "global":
                global_synced = await self.bot.tree.sync()
                self.bot.tree.copy_global_to(guild=guild_obj)
                guild_synced = await self.bot.tree.sync(guild=guild_obj)
                synced = guild_synced
                scope = f"global + guild mirror ({len(global_synced)} global)"
            elif mode_value == "clear":
                self.bot.tree.clear_commands(guild=guild_obj)
                self.bot.tree.copy_global_to(guild=guild_obj)
                synced = await self.bot.tree.sync(guild=guild_obj)
                scope = "guild (clear + copy global)"
            else:
                self.bot.tree.copy_global_to(guild=guild_obj)
                synced = await self.bot.tree.sync(guild=guild_obj)
                scope = "guild"
        except discord.HTTPException:
            log.exception("Manual command resync failed with mode=%s.", mode_value)
            await ctx.reply("Resync failed — check logs for details.", mention_author=False)
            return

        log.info(
            "Manual resync by %s (%s) mode=%s synced=%s.",
            ctx.author,
            ctx.author.id,
            mode_value,
            len(synced),
        )
        await ctx.reply(
            f"Resync complete for **{scope}**. Synced **{len(synced)}** command(s).",
            mention_author=False,
        )

    @commands.command(name="domme")
    async def domme(
        self,
        ctx: commands.Context[commands.Bot],
        *args: str,
    ) -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.reply("This command can only be used in a server channel.", mention_author=False)
            return

        action: str | None = None
        target_member: discord.Member | None = None

        for arg in args:
            resolved = None
            if arg.startswith("<@") and arg.endswith(">"):
                uid_str = arg[2:-1].lstrip("!")
                try:
                    uid = int(uid_str)
                    resolved = ctx.guild.get_member(uid)
                except ValueError:
                    pass
            else:
                try:
                    uid = int(arg)
                    resolved = ctx.guild.get_member(uid)
                except ValueError:
                    pass

            if resolved is not None:
                target_member = resolved
            else:
                action = arg

        content, embed, view, is_public, _ = await self._build_domme_response(
            member=ctx.author,
            guild=ctx.guild,
            action=action,
            target_member=target_member,
        )
        reply = await ctx.reply(
            content=content,
            embed=embed,
            view=view,
            mention_author=False,
        )
        if view is not None and hasattr(view, "message"):
            view.message = reply

    @app_commands.command(
        name="domme",
        description="Shows your Domme profile, starts setup, or edits your profile in DMs.",
    )
    @app_commands.describe(
        action="What to do: delete your profile, or show a leaderboard.",
        user="View another member's Domme profile or their leaderboard.",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Delete profile", value="delete"),
            app_commands.Choice(name="Show leaderboard", value="leaderboard"),
        ]
    )
    async def domme_slash(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str] | None = None,
        user: discord.Member | None = None,
    ) -> None:
        # DM context — start edit flow directly
        if interaction.guild is None:
            guild = self.bot.get_guild(self.config.guild_id)
            if guild is None:
                await interaction.response.send_message(
                    "I couldn't find the configured server.",
                    ephemeral=True,
                )
                return
            member = guild.get_member(interaction.user.id)
            if member is None:
                try:
                    member = await guild.fetch_member(interaction.user.id)
                except discord.NotFound:
                    member = None
                except (discord.Forbidden, discord.HTTPException):
                    await interaction.response.send_message(
                        "I couldn't verify your server membership right now. Please try again in a moment.",
                        ephemeral=True,
                    )
                    return
            domme_role = guild.get_role(self.config.domme_role_id)
            if member is None or domme_role is None or domme_role not in member.roles:
                await interaction.response.send_message(
                    "Only members with the Domme role can use this command.",
                    ephemeral=True,
                )
                return
            if interaction.user.id in self.domme_service.sessions:
                await interaction.response.send_message(
                    "You already have a setup in progress — scroll up to find it.",
                    ephemeral=True,
                )
                return
            await self.domme_service.start_setup_in_dm(interaction.user, interaction)
            return

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This command can only be used in a server channel or DM.",
                ephemeral=True,
            )
            return

        content, embed, view, is_public, leaderboard_embed = await self._build_domme_response(
            member=interaction.user,
            guild=interaction.guild,
            action=action.value if action else None,
            target_member=user,
        )
        response_kwargs: dict[str, object] = {
            "content": content,
            "embed": embed,
            "ephemeral": not is_public,
        }
        if view is not None:
            response_kwargs["view"] = view
        await interaction.response.send_message(
            **response_kwargs,
        )
        if view is not None and hasattr(view, "message"):
            view.message = await interaction.original_response()
        # Show personal leaderboard as ephemeral follow-up to the domme themselves
        if leaderboard_embed is not None:
            await interaction.followup.send(embed=leaderboard_embed, ephemeral=True)

    @app_commands.command(
        name="sub",
        description="View or set up your sub profile. Works in DMs too.",
    )
    @app_commands.describe(action="Choose edit to update your profile, or delete to remove it.")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Edit profile", value="edit"),
            app_commands.Choice(name="Delete profile", value="delete"),
        ]
    )
    async def sub_slash(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str] | None = None,
    ) -> None:
        # DM context — start edit flow directly in DM
        if interaction.guild is None:
            guild = self.bot.get_guild(self.config.guild_id)
            if guild is None:
                await interaction.response.send_message(
                    "I couldn't find the configured server.",
                    ephemeral=True,
                )
                return
            member = guild.get_member(interaction.user.id)
            if member is None:
                try:
                    member = await guild.fetch_member(interaction.user.id)
                except discord.NotFound:
                    member = None
                except (discord.Forbidden, discord.HTTPException):
                    await interaction.response.send_message(
                        "I couldn't verify your server membership right now. Please try again in a moment.",
                        ephemeral=True,
                    )
                    return
            if member is None:
                await interaction.response.send_message(
                    "You must be a member of the server to use this command.",
                    ephemeral=True,
                )
                return
            if interaction.user.id in self.sub_service.sessions:
                await interaction.response.send_message(
                    "You already have a setup in progress — scroll up to find it.",
                    ephemeral=True,
                )
                return
            await self.sub_service.start_setup_in_dm(interaction.user, interaction)
            return

        # Server context
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This command can only be used in a server channel or DM.",
                ephemeral=True,
            )
            return

        member = interaction.user

        if action and action.value == "delete":
            profile = await self.database.get_sub_profile(user_id=member.id)
            if profile is None:
                await interaction.response.send_message(
                    "You don't have a saved sub profile to delete.",
                    ephemeral=True,
                )
                return
            view = SubDeleteConfirmView(self.sub_service, member.id)
            await interaction.response.send_message(
                "Are you sure you want to delete your sub profile?",
                view=view,
                ephemeral=True,
            )
            view.message = await interaction.original_response()
            return

        # edit action — send setup to DM
        if action and action.value == "edit":
            if member.id in self.sub_service.sessions:
                await interaction.response.send_message(
                    "You already have a setup in progress — check your DMs to continue.",
                    ephemeral=True,
                )
                return
            started = await self.sub_service.start_setup_via_server(member)
            if not started:
                await interaction.response.send_message(
                    messages.DM_FAILURE_RESPONSE,
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                "I've sent you a DM to edit your sub profile.",
                ephemeral=True,
            )
            return

        # No action specified — show existing profile or start setup via DM
        profile = await self.database.get_sub_profile(user_id=member.id)
        if profile is not None:
            is_verified = self._is_verified(member)
            rank = await self.database.get_sub_leaderboard_rank(user_id=member.id)
            embed = embeds.sub_profile_embed(profile, member, is_verified=is_verified, rank=rank)
            await interaction.response.send_message(embed=embed)
            return

        if member.id in self.sub_service.sessions:
            await interaction.response.send_message(
                "You already have a setup in progress — check your DMs to continue.",
                ephemeral=True,
            )
            return

        started = await self.sub_service.start_setup_via_server(member)
        if not started:
            await interaction.response.send_message(
                messages.DM_FAILURE_RESPONSE,
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "I've sent you a DM to set up your sub profile.",
            ephemeral=True,
        )

    @app_commands.command(
        name="reaction_role_setup",
        description="Mod-only: create a reaction-role embed and mappings.",
    )
    async def reaction_role_setup(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return
        if not has_admin_command_permissions(interaction.user, self.config):
            await interaction.response.send_message(
                messages.UNAUTHORISED_HELP_RESPONSE,
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(
            ReactionRoleSetupModal(
                self.reaction_role_service,
                default_channel_id=self.config.roles_channel_id,
            )
        )

    @app_commands.command(
        name="help",
        description="Shows commands available to you, based on your roles.",
    )
    async def help(self, interaction: discord.Interaction) -> None:
        is_domme = False
        is_sub = False
        is_moderator = False
        if isinstance(interaction.user, discord.Member):
            member = interaction.user
            is_moderator = has_admin_command_permissions(member, self.config)
            if self.config.domme_role_id:
                is_domme = any(role.id == self.config.domme_role_id for role in member.roles)
            if self.config.submissive_role_id:
                is_sub = any(role.id == self.config.submissive_role_id for role in member.roles)

        pages = embeds.build_help_pages(
            is_domme=is_domme,
            is_sub=is_sub,
            is_moderator=is_moderator,
        )
        view = HelpView(interaction.user.id, pages=pages)
        await interaction.response.send_message(
            embed=embeds.help_page_embed(view.current_page, view.total_pages, pages),
            view=view,
            ephemeral=True,
        )

    def _is_verified(self, member: discord.Member) -> bool:
        """Return True if the member has the configured verified role."""
        verified_role = member.guild.get_role(self.config.verified_role_id) if self.config.verified_role_id else None
        return verified_role is not None and verified_role in member.roles

    async def _build_domme_response(
        self,
        *,
        member: discord.Member,
        guild: discord.Guild,
        action: str | None,
        target_member: discord.Member | None = None,
    ) -> tuple[str | None, discord.Embed | None, discord.ui.View | None, bool, discord.Embed | None]:
        """Return (content, embed, view, is_public, leaderboard_embed).

        leaderboard_embed is only set when the caller is viewing their own profile and has sends.
        """
        domme_role = guild.get_role(self.config.domme_role_id)
        if domme_role is None:
            return "I couldn't find the configured Domme role.", None, None, False, None

        if domme_role not in member.roles:
            return "Only members with the Domme role can use this command.", None, None, False, None

        requested_action = (action or "").strip().lower()

        # Leaderboard action — show a domme's throne leaderboard publicly
        if requested_action == "leaderboard":
            target = target_member if target_member and target_member != member else member
            target_profile = await self.database.get_domme_profile(user_id=target.id)
            if target_profile is None:
                name = target.display_name if target != member else "You"
                suffix = "doesn't have a Domme profile." if target != member else "don't have a Domme profile yet."
                return f"{name} {suffix}", None, None, False, None
            sends = await self.database.get_sends_for_domme(domme_user_id=target.id)
            leaderboard_embed = embeds.domme_send_leaderboard_embed(sends, target)
            return None, leaderboard_embed, None, True, None

        # Viewing another member's profile
        if target_member is not None and target_member != member:
            profile = await self.database.get_domme_profile(user_id=target_member.id)
            if profile is None:
                return f"{target_member.display_name} doesn't have a Domme profile saved.", None, None, False, None
            is_verified = self._is_verified(target_member)
            embed = embeds.domme_profile_embed(profile, target_member, is_verified=is_verified)
            view = _tribute_view(profile)
            return None, embed, view, True, None

        profile = await self.database.get_domme_profile(user_id=member.id)

        if requested_action == "delete":
            if profile is None:
                return "You do not have a saved Domme profile to delete.", None, None, False, None
            return (
                "Are you sure you want to delete your Domme profile?",
                None,
                DommeDeleteConfirmView(self.domme_service, member.id),
                False,
                None,
            )

        if profile is not None:
            is_verified = self._is_verified(member)
            embed = embeds.domme_profile_embed(profile, member, is_verified=is_verified)
            view = _tribute_view(profile)
            # Personal leaderboard as ephemeral follow-up
            leaderboard_embed: discord.Embed | None = None
            sends = await self.database.get_sends_for_domme(domme_user_id=member.id)
            if sends:
                leaderboard_embed = embeds.domme_send_leaderboard_embed(sends, member)
            return None, embed, view, True, leaderboard_embed

        if member.id in self.domme_service.sessions:
            return (
                "You already have a setup in progress — check your DMs to continue.",
                None,
                None,
                False,
                None,
            )

        started = await self.domme_service.start_setup(member)
        if not started:
            return messages.DM_FAILURE_RESPONSE, None, None, False, None

        return "I've sent you a DM to set up your Domme profile.", None, None, False, None
