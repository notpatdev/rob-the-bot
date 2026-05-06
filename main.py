from __future__ import annotations

import logging
import os
import sys

import discord
from discord.ext import commands

from bot.config import BotConfig, load_config
from bot.database import Database
from bot.event_cog import RobEventCog
from bot.throne_tracker import ThroneTrackerCog


class RobBot(commands.Bot):
    def __init__(self, config: BotConfig, database: Database) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.message_content = True
        intents.dm_messages = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=True,
                everyone=False,
            ),
        )
        self.config = config
        self.database = database

    async def setup_hook(self) -> None:
        await self.database.initialize()

        event_cog = RobEventCog(self, self.config, self.database)
        await self.add_cog(event_cog)
        await event_cog.restore_runtime()

        await self.add_cog(ThroneTrackerCog(self, self.config, self.database))

        if self.config.guild_id:
            guild = discord.Object(id=self.config.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logging.info("Synced %s guild command(s).", len(synced))
        else:
            synced = await self.tree.sync()
            logging.info("Synced %s global command(s).", len(synced))

    async def on_ready(self) -> None:
        logging.info("%s is online as %s.", self.config.bot_name, self.user)

    async def close(self) -> None:
        await self.database.close()
        await super().close()


def configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    if sys.version_info < (3, 11):
        raise RuntimeError("Rob requires Python 3.11 or newer.")

    configure_logging()
    config = load_config()
    database = Database(config.database_path)
    bot = RobBot(config, database)
    bot.run(config.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
