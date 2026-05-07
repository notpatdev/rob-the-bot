# Rob the Bot

Rob is a Discord bot for running a server event with Components V2 cards, event registration, live leaderboards, and automated Throne send tracking.

The current runtime is event-first:

- `!import` for channel and role configuration
- `!event start`, `!event end`, and `!event status`
- `/register action:domme`
- `/register action:sub`
- leaderboard channel sync
- send-track notifications
- owner restart notification

The repo also ships a shared Components V2 UI layer for verification, help, and profile flows in [`bot/views.py`](/Users/patfaint/Documents/Codex/rob-the-bot-components-v2/bot/views.py) and [`bot/ui/`](/Users/patfaint/Documents/Codex/rob-the-bot-components-v2/bot/ui/__init__.py). The main bot UI is built with `discord.ui.LayoutView`, `Container`, `Section`, `TextDisplay`, `Separator`, `Thumbnail`, `MediaGallery`, and `Button`. Main bot screens do not use classic `discord.Embed`.

## Features

- Discord Components V2 cards throughout the main UI
- In-card action buttons via `Section(..., accessory=button)` where it improves the layout
- Moderator event controls with clear start/end/status cards
- Registration flow for Dommes and Subs
- Automatic Throne polling and send detection
- Live sub leaderboard and Domme totals messages
- Send-track notifications with item thumbnails when available
- Shared reusable UI helpers under [`bot/ui/`](/Users/patfaint/Documents/Codex/rob-the-bot-components-v2/bot/ui/__init__.py)
- `!import` flow for loading server IDs into [`bot/channels.py`](/Users/patfaint/Documents/Codex/rob-the-bot-components-v2/bot/channels.py)

## Project Structure

```text
.
├── README.md
├── requirements.txt
├── .env.example
├── install.sh
├── main.py
├── rob-the-bot.service
├── bot/
│   ├── __init__.py
│   ├── channels.py
│   ├── config.py
│   ├── database.py
│   ├── event_cog.py
│   ├── event_views.py
│   ├── throne_scraper.py
│   ├── throne_tracker.py
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── cards.py
│   │   ├── components.py
│   │   ├── copy.py
│   │   └── theme.py
│   ├── utils.py
│   └── views.py
└── data/
    └── .gitkeep
```

## Requirements

- Python 3.11+
- `discord.py>=2.7.1,<3`

## Local Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

Set `DISCORD_TOKEN` in `.env` before starting the bot.

Server-specific IDs live in [`bot/channels.py`](/Users/patfaint/Documents/Codex/rob-the-bot-components-v2/bot/channels.py). You can either edit that file directly or use `!import` in Discord to save them from a guided form.

## Configuration

Environment variables from [`.env.example`](/Users/patfaint/Documents/Codex/rob-the-bot-components-v2/.env.example):

```env
DISCORD_TOKEN=
BOT_NAME=Rob
EVENT_NAME=Mother's Day Event
DATABASE_PATH=/opt/rob-the-bot/data/rob_the_bot.sqlite3
THRONE_POLL_INTERVAL_SECONDS=60
THRONE_POLL_PER_DOMME_DELAY_SECONDS=3
THRONE_HTTP_TIMEOUT_SECONDS=10
THRONE_USER_AGENT=
```

Channel and role IDs are loaded from [`bot/channels.py`](/Users/patfaint/Documents/Codex/rob-the-bot-components-v2/bot/channels.py):

- `GUILD_ID`
- `REGISTRATION_CHANNEL_ID`
- `LEADERBOARD_CHANNEL_ID`
- `SEND_TRACK_CHANNEL_ID`
- `DOMME_ROLE_ID`
- `SUBMISSIVE_ROLE_ID`
- `MODERATION_ROLE_ID`
- `EVENT_BAN_ROLE_ID`

## Commands

Prefix commands:

- `!import`
  Opens the Components V2 configuration prompt and saves channel/role IDs.
- `!event start`
  Opens the event end-time picker.
- `!event end`
  Opens the confirmation card for ending the event early.
- `!event status`
  Shows the current event state, registrations, and send totals.

Slash commands:

- `/register action:domme`
  Register as a Domme for the event.
- `/register action:sub`
  Register as a Sub and link your sending name for the leaderboard.

## UI Notes

- Main bot cards use Components V2 layouts, not classic embeds.
- Buttons live inside cards where that improves the experience.
- Navigation buttons for things like help pagination can still sit below the card when that is clearer.
- Shared UI helpers live in [`bot/ui/components.py`](/Users/patfaint/Documents/Codex/rob-the-bot-components-v2/bot/ui/components.py).
- Shared reusable card builders live in [`bot/ui/cards.py`](/Users/patfaint/Documents/Codex/rob-the-bot-components-v2/bot/ui/cards.py).

## Validation

Useful checks after UI work:

```bash
python3 -m compileall bot main.py
python3 - <<'PY'
import sys
sys.path.insert(0, ".")
import discord
from bot import views
from bot import event_views
print("imports OK")
PY
grep -R "discord.Embed\\|embed=\\|embeds=" -n bot main.py || true
```

## Production Install

The included installer bootstraps a Linux host:

```bash
sudo bash install.sh
```

It creates the runtime environment, installs dependencies, writes `.env`, and configures the `rob-the-bot` systemd service.
