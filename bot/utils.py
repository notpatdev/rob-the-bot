"""Shared utility helpers used across the bot."""
from __future__ import annotations

import discord

from bot.config import BotConfig


def has_moderation_role(member: discord.Member, config: BotConfig) -> bool:
    return any(role.id == config.moderation_role_id for role in member.roles)


def has_admin_command_permissions(member: discord.Member, config: BotConfig) -> bool:
    if member.guild_permissions.administrator:
        return True
    return has_moderation_role(member, config)


def mention_channel(channel_id: int) -> str:
    return f"<#{channel_id}>"


def user_mention(user_id: int) -> str:
    return f"<@{user_id}>"
