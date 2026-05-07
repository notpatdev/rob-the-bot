"""Components V2 views and modals for Rob the Bot.

All UI is built with discord.ui.LayoutView + Container/TextDisplay/Section/
Separator/Thumbnail — no classic embeds are used anywhere.

The Section(text, accessory=button) pattern puts buttons visually inside the
card, aligned to the right of the accompanying text, matching the style shown
in the screenshot the user provided.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from bot.event_cog import RobEventCog

log = logging.getLogger(__name__)

# ─── Colour palette ───────────────────────────────────────────────────────────
PURPLE = discord.Colour.from_rgb(139, 92, 246)   # leaderboard / accent
GREEN  = discord.Colour.from_rgb(34, 197, 94)    # success / sends
RED    = discord.Colour.from_rgb(220, 38, 38)    # danger / end event
BLUE   = discord.Colour.from_rgb(59, 130, 246)   # info / domme totals
GOLD   = discord.Colour.from_rgb(234, 179, 8)    # update notification


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _medal(rank: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"**#{rank}**")


def format_money(amount: float | None) -> str:
    if amount is None:
        return "Unknown"
    return f"${amount:,.2f}"


def _simple_view(text: str, *, colour: discord.Colour = GREEN, timeout: float = 60) -> discord.ui.LayoutView:
    """Tiny helper: a LayoutView containing a single-text Container."""
    view = discord.ui.LayoutView(timeout=timeout)
    view.add_item(discord.ui.Container(discord.ui.TextDisplay(text), accent_color=colour))
    return view


# ─── Modals ───────────────────────────────────────────────────────────────────

class DommeSignupModal(discord.ui.Modal, title="Domme Sign-Up"):
    """Modal that collects a Throne username or link."""

    throne_input: discord.ui.TextInput = discord.ui.TextInput(
        label="Throne username or link",
        placeholder="e.g.  mistressxxx   or   https://throne.com/mistressxxx",
        min_length=2,
        max_length=200,
    )

    def __init__(self, cog: RobEventCog) -> None:
        super().__init__(timeout=300)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.process_domme_signup(interaction, self.throne_input.value)


class SubSignupModal(discord.ui.Modal, title="Sub Sign-Up"):
    """Modal that collects the sub's Throne sending name."""

    name_input: discord.ui.TextInput = discord.ui.TextInput(
        label="Your Throne sending name",
        placeholder="The name you use when sending on Throne",
        min_length=1,
        max_length=100,
    )

    def __init__(self, cog: RobEventCog) -> None:
        super().__init__(timeout=300)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.process_sub_signup(interaction, self.name_input.value)


class EventStartModal(discord.ui.Modal, title="Set Event End Time"):
    """Modal that collects the event end date and time."""

    date_input: discord.ui.TextInput = discord.ui.TextInput(
        label="End date (YYYY-MM-DD)",
        placeholder="e.g.  2025-05-12",
        min_length=10,
        max_length=10,
    )
    time_input: discord.ui.TextInput = discord.ui.TextInput(
        label="End time (HH:MM — 24 h, AEST/Sydney)",
        placeholder="e.g.  23:59",
        min_length=5,
        max_length=5,
    )

    def __init__(self, cog: RobEventCog) -> None:
        super().__init__(timeout=300)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.process_event_start_modal(
            interaction,
            end_date=self.date_input.value,
            end_time=self.time_input.value,
        )


class ImportChannelsModal(discord.ui.Modal, title="Configure — Channels & Guild"):
    """Step 1 of 2: channel IDs and guild ID."""

    guild_id_field: discord.ui.TextInput = discord.ui.TextInput(
        label="Guild (Server) ID",
        placeholder="Right-click the server → Copy Server ID",
        min_length=17,
        max_length=20,
    )
    reg_channel: discord.ui.TextInput = discord.ui.TextInput(
        label="Registration Channel ID",
        placeholder="1234567890123456789",
        min_length=17,
        max_length=20,
    )
    lb_channel: discord.ui.TextInput = discord.ui.TextInput(
        label="Leaderboard Channel ID",
        placeholder="1234567890123456789",
        min_length=17,
        max_length=20,
    )
    send_channel: discord.ui.TextInput = discord.ui.TextInput(
        label="Send-Track Channel ID",
        placeholder="1234567890123456789",
        min_length=17,
        max_length=20,
    )
    mod_role: discord.ui.TextInput = discord.ui.TextInput(
        label="Moderation Role ID",
        placeholder="1234567890123456789",
        min_length=17,
        max_length=20,
    )

    def __init__(self, cog: RobEventCog, prefill_guild_id: int) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        if prefill_guild_id:
            self.guild_id_field.default = str(prefill_guild_id)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            guild_id = int(self.guild_id_field.value.strip())
            reg = int(self.reg_channel.value.strip())
            lb = int(self.lb_channel.value.strip())
            send = int(self.send_channel.value.strip())
            mod = int(self.mod_role.value.strip())
        except ValueError:
            await interaction.response.send_message(
                "All IDs must be numeric. Please try again.", ephemeral=True
            )
            return
        await interaction.response.send_modal(
            ImportRolesModal(
                self.cog,
                guild_id=guild_id,
                registration_channel_id=reg,
                leaderboard_channel_id=lb,
                send_track_channel_id=send,
                moderation_role_id=mod,
            )
        )


class ImportRolesModal(discord.ui.Modal, title="Configure — Roles"):
    """Step 2 of 2: role IDs."""

    domme_role: discord.ui.TextInput = discord.ui.TextInput(
        label="Domme Role ID",
        placeholder="1234567890123456789",
        min_length=17,
        max_length=20,
    )
    sub_role: discord.ui.TextInput = discord.ui.TextInput(
        label="Submissive Role ID",
        placeholder="1234567890123456789",
        min_length=17,
        max_length=20,
    )
    ban_role: discord.ui.TextInput = discord.ui.TextInput(
        label="Event Ban Role ID (optional — leave blank to skip)",
        placeholder="1234567890123456789",
        required=False,
        max_length=20,
    )

    def __init__(
        self,
        cog: RobEventCog,
        *,
        guild_id: int,
        registration_channel_id: int,
        leaderboard_channel_id: int,
        send_track_channel_id: int,
        moderation_role_id: int,
    ) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self._guild_id = guild_id
        self._registration_channel_id = registration_channel_id
        self._leaderboard_channel_id = leaderboard_channel_id
        self._send_track_channel_id = send_track_channel_id
        self._moderation_role_id = moderation_role_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            domme = int(self.domme_role.value.strip())
            sub = int(self.sub_role.value.strip())
        except ValueError:
            await interaction.response.send_message(
                "Role IDs must be numeric. Please try again.", ephemeral=True
            )
            return
        ban_str = self.ban_role.value.strip()
        ban = int(ban_str) if ban_str.isdigit() else 0
        await self.cog.save_config_ids(
            interaction=interaction,
            guild_id=self._guild_id,
            registration_channel_id=self._registration_channel_id,
            leaderboard_channel_id=self._leaderboard_channel_id,
            send_track_channel_id=self._send_track_channel_id,
            moderation_role_id=self._moderation_role_id,
            domme_role_id=domme,
            submissive_role_id=sub,
            event_ban_role_id=ban,
        )


# ─── Command-response LayoutViews ─────────────────────────────────────────────

class EventStartPromptView(discord.ui.LayoutView):
    """Sent in reply to !event start — button opens EventStartModal."""

    def __init__(self, cog: RobEventCog, *, owner_id: int) -> None:
        super().__init__(timeout=900)
        self.cog = cog
        self.owner_id = owner_id

        btn = discord.ui.Button(
            label="Set End Time",
            style=discord.ButtonStyle.primary,
            emoji="🗓️",
        )
        btn.callback = self._set_end_time

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"## 🚀 Start Event — {cog.config.event_name}\n\n"
                    "Set the date and time the event will end. "
                    "Times are entered in **AEST (UTC+10 / Sydney)**."
                ),
                discord.ui.Separator(),
                discord.ui.Section(
                    "Open the date & time picker to get started.",
                    accessory=btn,
                ),
                accent_color=PURPLE,
            )
        )

    async def _set_end_time(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the person who ran this command can use this button.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(EventStartModal(self.cog))


class EventEndConfirmView(discord.ui.LayoutView):
    """Sent in reply to !event end — two in-card buttons: confirm or cancel."""

    def __init__(self, cog: RobEventCog, *, owner_id: int) -> None:
        super().__init__(timeout=900)
        self.cog = cog
        self.owner_id = owner_id

        end_btn = discord.ui.Button(
            label="End Event",
            style=discord.ButtonStyle.danger,
            emoji="⛔",
        )
        end_btn.callback = self._end_event

        cancel_btn = discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.secondary,
        )
        cancel_btn.callback = self._cancel

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"## ⚠️ End Event Early?\n\n"
                    f"This will end **{cog.config.event_name}** right now and freeze "
                    "the leaderboards. This cannot be undone."
                ),
                discord.ui.Separator(),
                discord.ui.Section("Confirm ending the event immediately.", accessory=end_btn),
                discord.ui.Section("Changed your mind?", accessory=cancel_btn),
                accent_color=RED,
            )
        )

    async def _end_event(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the person who ran this command can use this button.",
                ephemeral=True,
            )
            return
        await self.cog.process_event_end(interaction)

    async def _cancel(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the person who ran this command can use this button.",
                ephemeral=True,
            )
            return
        self.stop()
        await interaction.response.edit_message(
            view=_simple_view("Event end cancelled.", colour=BLUE),
        )


class ImportPromptView(discord.ui.LayoutView):
    """Sent in reply to !import id — button opens ImportChannelsModal."""

    def __init__(self, cog: RobEventCog, *, owner_id: int, guild_id: int) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id

        btn = discord.ui.Button(
            label="Configure IDs",
            style=discord.ButtonStyle.primary,
            emoji="⚙️",
        )
        btn.callback = self._configure

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    "## ⚙️ Configure Channel & Role IDs\n\n"
                    "Two forms will open in sequence. Fill in your server's channel and "
                    "role IDs — the configuration is saved to the database immediately."
                ),
                discord.ui.Separator(),
                discord.ui.Section("Open the configuration forms.", accessory=btn),
                accent_color=BLUE,
            )
        )

    async def _configure(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the person who ran this command can use this button.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(
            ImportChannelsModal(self.cog, prefill_guild_id=self.guild_id)
        )


# ─── Leaderboard channel views (no buttons — auto-updated, timeout=None) ──────

class SubLeaderboardView(discord.ui.LayoutView):
    """Message 1 in the leaderboard channel: sub rankings + event status."""

    def __init__(
        self,
        *,
        event_name: str,
        state: object,  # EventState
        rows: list[tuple[str, float, int]],   # (mention, total_usd, send_count)
        unclaimed_total: float,
    ) -> None:
        super().__init__(timeout=None)

        # ── Status line ──────────────────────────────────────────────────────
        is_active = getattr(state, "is_active", False)
        ends_at_iso = getattr(state, "ends_at", None)
        ended_at_iso = getattr(state, "ended_at", None)

        if is_active and ends_at_iso:
            try:
                ts = int(datetime.fromisoformat(ends_at_iso).timestamp())
                status = f"🟢 Active — ends <t:{ts}:R>"
            except ValueError:
                status = "🟢 Active"
        elif ended_at_iso:
            try:
                ts = int(datetime.fromisoformat(ended_at_iso).timestamp())
                status = f"🔴 Event ended <t:{ts}:F>"
            except ValueError:
                status = "🔴 Event ended"
        else:
            status = "⚪ Event not started yet"

        # ── Rankings text ─────────────────────────────────────────────────────
        if rows:
            lines: list[str] = []
            for i, (mention, total, sends) in enumerate(rows, 1):
                suffix = "send" if sends == 1 else "sends"
                lines.append(
                    f"{_medal(i)} {mention} — **{format_money(total)}** ({sends} {suffix})"
                )
            rankings_text = "\n".join(lines)
            if len(rows) >= 20:
                rankings_text += (
                    "\n\n-# Showing top 20. Use `/register action:sub` to get on the board."
                )
        else:
            rankings_text = (
                "*No ranked subs yet.*\n"
                "-# Subs: use `/register action:sub` to link your Throne name."
            )

        # ── Build container ───────────────────────────────────────────────────
        components: list[discord.ui.Item] = [
            discord.ui.TextDisplay(f"## 🏆 {event_name} — Sub Leaderboard\n{status}"),
            discord.ui.Separator(),
            discord.ui.TextDisplay(rankings_text),
        ]
        if unclaimed_total > 0.01:
            components.append(discord.ui.Separator())
            components.append(
                discord.ui.TextDisplay(
                    f"-# 💬 {format_money(unclaimed_total)} in sends is unclaimed — "
                    "those subs haven't registered yet."
                )
            )

        self.add_item(discord.ui.Container(*components, accent_color=PURPLE))


class DommeTotalsView(discord.ui.LayoutView):
    """Message 2 in the leaderboard channel: domme totals."""

    def __init__(
        self,
        *,
        rows: list[tuple[str, float, int]],   # (mention, total_usd, send_count)
    ) -> None:
        super().__init__(timeout=None)

        if rows:
            lines: list[str] = []
            for i, (mention, total, sends) in enumerate(rows, 1):
                suffix = "send" if sends == 1 else "sends"
                lines.append(
                    f"{_medal(i)} {mention} — **{format_money(total)}** ({sends} {suffix})"
                )
            totals_text = "\n".join(lines)
        else:
            totals_text = "*No sends tracked yet.*"

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay("## 🌸 Domme Totals"),
                discord.ui.Separator(),
                discord.ui.TextDisplay(totals_text),
                accent_color=BLUE,
            )
        )


# ─── Send-track channel view ───────────────────────────────────────────────────

class SendNotificationView(discord.ui.LayoutView):
    """Posted to the send-track channel when a new Throne send is detected."""

    def __init__(
        self,
        *,
        sub_label: str,
        domme_label: str,
        amount_label: str,
        item_name: str | None,
        item_image_url: str | None,
        sub_rank: int | None,
        domme_send_count: int,
    ) -> None:
        super().__init__(timeout=None)

        details_lines = [
            f"**Sub:** {sub_label}",
            f"**Domme:** {domme_label}",
            f"**Amount:** {amount_label}",
        ]
        if item_name:
            details_lines.append(f"**Item:** {item_name}")

        footer_parts: list[str] = []
        if sub_rank is not None:
            footer_parts.append(f"Sub rank: **#{sub_rank}**")
        footer_parts.append(f"Domme total sends: **{domme_send_count}**")
        footer_text = " · ".join(footer_parts)

        components: list[discord.ui.Item] = [
            discord.ui.TextDisplay("## 💵 New Send!"),
            discord.ui.Separator(),
        ]

        if item_image_url:
            # Section puts the thumbnail accessory on the right inside the card
            components.append(
                discord.ui.Section(
                    "\n".join(details_lines),
                    accessory=discord.ui.Thumbnail(item_image_url),
                )
            )
        else:
            components.append(discord.ui.TextDisplay("\n".join(details_lines)))

        if footer_text:
            components.append(discord.ui.Separator())
            components.append(discord.ui.TextDisplay(f"-# {footer_text}"))

        self.add_item(discord.ui.Container(*components, accent_color=GREEN))


# ─── Event status view (ephemeral reply to !event status) ─────────────────────

class EventStatusView(discord.ui.LayoutView):
    """Ephemeral reply to !event status."""

    def __init__(
        self,
        *,
        event_name: str,
        state: object,   # EventState
        domme_count: int,
        sub_count: int,
        send_count: int,
        send_total_usd: float,
    ) -> None:
        super().__init__(timeout=60)

        is_active = getattr(state, "is_active", False)
        ends_at_iso = getattr(state, "ends_at", None)
        ended_at_iso = getattr(state, "ended_at", None)

        if is_active and ends_at_iso:
            try:
                ts = int(datetime.fromisoformat(ends_at_iso).timestamp())
                status_line = f"🟢 **Active** — ends <t:{ts}:R> (<t:{ts}:F>)"
            except ValueError:
                status_line = "🟢 **Active**"
        elif ended_at_iso:
            try:
                ts = int(datetime.fromisoformat(ended_at_iso).timestamp())
                status_line = f"🔴 **Ended** <t:{ts}:F>"
            except ValueError:
                status_line = "🔴 **Ended**"
        else:
            status_line = "⚪ **Not started**"

        body = (
            f"## 📊 Event Status — {event_name}\n\n"
            f"{status_line}\n\n"
            f"**Dommes registered:** {domme_count}\n"
            f"**Subs registered:** {sub_count}\n"
            f"**Total sends:** {send_count} — {format_money(send_total_usd)}"
        )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(body),
                accent_color=BLUE,
            )
        )


# ─── Owner DM: update notification ────────────────────────────────────────────

class UpdateNotificationView(discord.ui.LayoutView):
    """DM'd to the bot owner on every startup. Acknowledge button dismisses it."""

    def __init__(self) -> None:
        super().__init__(timeout=86400)  # 24 h — not persistent, new one sent each restart

        now_ts = int(datetime.now(timezone.utc).timestamp())

        ack_btn = discord.ui.Button(
            label="Acknowledge",
            style=discord.ButtonStyle.success,
            emoji="✓",
        )
        ack_btn.callback = self._acknowledge

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    "## ✅ Bot Restarted\n\n"
                    f"Rob came back online <t:{now_ts}:R>.\n"
                    "If this was triggered by a GitHub Actions deploy, "
                    "the latest code is now running."
                ),
                discord.ui.Separator(),
                discord.ui.Section("Tap to dismiss this notification.", accessory=ack_btn),
                accent_color=GOLD,
            )
        )

    async def _acknowledge(self, interaction: discord.Interaction) -> None:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        await interaction.response.edit_message(
            view=_simple_view(
                f"✅ Acknowledged <t:{now_ts}:R>.",
                colour=GREEN,
                timeout=1,
            )
        )
