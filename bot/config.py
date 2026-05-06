from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from bot import channels


@dataclass(frozen=True)
class BotConfig:
    bot_name: str
    event_name: str
    discord_token: str
    guild_id: int
    registration_channel_id: int
    domme_role_id: int
    submissive_role_id: int
    moderation_role_id: int
    event_ban_role_id: int
    leaderboard_channel_id: int
    send_track_channel_id: int
    database_path: Path
    throne_poll_interval_seconds: int
    throne_poll_per_domme_delay_seconds: float
    throne_http_timeout_seconds: float
    throne_user_agent: str


_DEFAULT_THRONE_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 RobBot/1.0"
)


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, value)


def load_config() -> BotConfig:
    load_dotenv()

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Missing required environment variable: DISCORD_TOKEN")

    return BotConfig(
        bot_name=os.getenv("BOT_NAME", "Rob"),
        event_name=os.getenv("EVENT_NAME", "Mother's Day Event"),
        discord_token=token,
        guild_id=channels.GUILD_ID,
        registration_channel_id=channels.REGISTRATION_CHANNEL_ID,
        domme_role_id=channels.DOMME_ROLE_ID,
        submissive_role_id=channels.SUBMISSIVE_ROLE_ID,
        moderation_role_id=channels.MODERATION_ROLE_ID,
        event_ban_role_id=getattr(channels, "EVENT_BAN_ROLE_ID", 0),
        leaderboard_channel_id=channels.LEADERBOARD_CHANNEL_ID,
        send_track_channel_id=channels.SEND_TRACK_CHANNEL_ID,
        database_path=Path(os.getenv("DATABASE_PATH", "/opt/rob-the-bot/data/rob_the_bot.sqlite3")),
        throne_poll_interval_seconds=_env_int("THRONE_POLL_INTERVAL_SECONDS", 30, minimum=30),
        throne_poll_per_domme_delay_seconds=_env_float(
            "THRONE_POLL_PER_DOMME_DELAY_SECONDS", 3.0, minimum=0.0
        ),
        throne_http_timeout_seconds=_env_float(
            "THRONE_HTTP_TIMEOUT_SECONDS", 10.0, minimum=1.0
        ),
        throne_user_agent=os.getenv("THRONE_USER_AGENT") or _DEFAULT_THRONE_USER_AGENT,
    )
