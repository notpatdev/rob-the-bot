from __future__ import annotations

import discord

from bot.database import EventDommeTotalRow, EventSubTotalRow

ACCENT = discord.Color.from_rgb(139, 92, 246)
SUCCESS = discord.Color.from_rgb(34, 197, 94)
INFO = discord.Color.from_rgb(59, 130, 246)


def _set_footer(embed: discord.Embed, *, server_name: str) -> discord.Embed:
    embed.set_footer(text=f"Made by Pat (notpatdev) | {server_name}")
    return embed


def registration_embed(*, bot_name: str, event_name: str, server_name: str) -> discord.Embed:
    embed = discord.Embed(
        title="Mothers Day Event Registration",
        description=(
            f"I’m {bot_name}. During the event I’ll keep track of Throne sends and update the "
            "leaderboards automatically.\n\n"
            "**Dommes**\n"
            "Click **Domme Sign Up** and enter your Throne username or your Throne link. "
            "Once you're in, I'll watch that Throne for new sends.\n\n"
            "**Subs**\n"
            "Click **Sub Sign Up** and enter the name you want tracked. Use that same name "
            "when you send on Throne so I can match it to you.\n\n"
            "Sub names are case-insensitive and each name can only belong to one person."
        ),
        color=ACCENT,
    )
    return _set_footer(embed, server_name=server_name)


def domme_signup_success_embed(*, throne_url: str, server_name: str) -> discord.Embed:
    embed = discord.Embed(
        title="You're signed up",
        description=(
            "I'll track sends for this Throne account:\n"
            f"{throne_url}"
        ),
        color=SUCCESS,
    )
    return _set_footer(embed, server_name=server_name)


def sub_signup_success_embed(*, sub_name: str, server_name: str) -> discord.Embed:
    embed = discord.Embed(
        title="You're signed up",
        description=(
            "You're registered for the event as:\n"
            f"**{sub_name}**\n\n"
            "Use that exact name on Throne and I'll attach sends to you automatically."
        ),
        color=SUCCESS,
    )
    return _set_footer(embed, server_name=server_name)


def botinfo_embed(*, bot_name: str, event_name: str, poll_seconds: int, server_name: str) -> discord.Embed:
    embed = discord.Embed(
        title=bot_name,
        description=(
            f"{bot_name} is running the **{event_name}** Throne tracker.\n\n"
            f"Poll interval: **{poll_seconds} seconds**\n"
            "New sends are posted in the send-tracking channel and the leaderboard snapshots update automatically."
        ),
        color=INFO,
    )
    return _set_footer(embed, server_name=server_name)


def event_start_prompt_embed(*, event_name: str, timezone_name: str, server_name: str) -> discord.Embed:
    embed = discord.Embed(
        title="Start Event",
        description=(
            f"Set the end date and time for **{event_name}**.\n\n"
            f"Use the button below, then enter the date and time in **{timezone_name}**."
        ),
        color=ACCENT,
    )
    return _set_footer(embed, server_name=server_name)


def event_started_embed(*, event_name: str, end_label: str, server_name: str) -> discord.Embed:
    embed = discord.Embed(
        title="Event Started",
        description=(
            f"**{event_name}** is now live.\n\n"
            f"It will end at {end_label}."
        ),
        color=SUCCESS,
    )
    return _set_footer(embed, server_name=server_name)


def event_end_confirm_embed(*, event_name: str, server_name: str) -> discord.Embed:
    embed = discord.Embed(
        title="End Event Early?",
        description=(
            f"This will end **{event_name}** right now and freeze the live leaderboard updates."
        ),
        color=INFO,
    )
    return _set_footer(embed, server_name=server_name)


def event_ended_embed(*, event_name: str, server_name: str) -> discord.Embed:
    embed = discord.Embed(
        title="Event Ended",
        description=(
            f"**{event_name}** has ended.\n\n"
            "The Domme leaderboard is now frozen and the Sub leaderboard shows the final top 5."
        ),
        color=INFO,
    )
    return _set_footer(embed, server_name=server_name)


def send_found_embed(
    *,
    sub_label: str,
    domme_label: str,
    amount_label: str,
    sub_nickname: str,
    sub_rank: int | None,
    domme_nickname: str,
    domme_send_count: int,
    server_name: str,
) -> discord.Embed:
    rank_text = str(sub_rank) if sub_rank is not None else "Unranked"
    embed = discord.Embed(
        title="💵 New Send Found 💵",
        description=(
            f"**Sub:** {sub_label}\n"
            f"**Domme:** {domme_label}\n"
            f"**Amount:** {amount_label}\n\n"
            f"**{sub_nickname}'s Leaderboard Rank:** {rank_text}\n"
            f"**{domme_nickname}'s total sends so far:** {domme_send_count}"
        ),
        color=SUCCESS,
    )
    return _set_footer(embed, server_name=server_name)


def sub_leaderboard_summary_embed(*, event_name: str, unclaimed_total: float, server_name: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"{event_name} - Sub Leaderboard",
        description=f"Unclaimed send amount: **{format_money(unclaimed_total)}**",
        color=ACCENT,
    )
    return _set_footer(embed, server_name=server_name)


def sub_leaderboard_page_embed(
    *,
    rows: list[tuple[str, EventSubTotalRow]],
    server_name: str,
) -> discord.Embed:
    if rows:
        description = "\n".join(
            f"{label}: **{format_money(row.total_usd)}**"
            for label, row in rows
        )
    else:
        description = "No claimed sends yet."

    embed = discord.Embed(
        description=description,
        color=ACCENT,
    )
    return _set_footer(embed, server_name=server_name)


def domme_totals_embed(*, event_name: str, rows: list[tuple[str, EventDommeTotalRow]], server_name: str) -> discord.Embed:
    if rows:
        blocks = [
            f"{label}: **{format_money(row.total_usd)}**\n"
            f"Total Sends: {row.send_count}"
            for label, row in rows
        ]
        description = "\n\n".join(blocks)
    else:
        description = "No sends tracked yet."

    embed = discord.Embed(
        title=f"{event_name} - Domme's Total Received",
        description=description,
        color=INFO,
    )
    return _set_footer(embed, server_name=server_name)


def format_money(amount: float | None) -> str:
    if amount is None:
        return "Unknown"
    return f"${amount:,.2f}"
