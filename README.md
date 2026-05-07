# Rob the Bot

Rob is a Discord bot for live Throne tracking, clean Components V2 leaderboard cards, event overlays, and send notifications that stay online even when no event is running.

## What Rob Does Now

- Tracks registered Domme Throne links all the time
- Posts send notifications to the send-tracking channel
- Keeps live Domme-first leaderboards updated in place
- Layers event-specific totals on top of the live tracker when a configured event window is active
- Posts a final event report once when an event ends
- Loads Discord IDs from [`bot/channels.py`](/Users/patfaint/Documents/Codex/rob-the-bot-components-v2/bot/channels.py)
- Loads event themes and windows from [`config/events.json`](/Users/patfaint/Documents/Codex/rob-the-bot-components-v2/config/events.json)
- Uses Discord Components V2 cards instead of classic embeds for the main bot UI

## Commands

Prefix commands:

- `!throne refresh`
  Run one manual Throne poll immediately.
- `!throne status`
  Show tracker health, cooldowns, and last poll state.
- `!event status`
  Show the currently loaded event config and active mode.
- `!event reload`
  Reload [`config/events.json`](/Users/patfaint/Documents/Codex/rob-the-bot-components-v2/config/events.json) without restarting the bot.
- `!event start`
  Explains that events are controlled from JSON now.
- `!event end`
  Explains that events are controlled from JSON now.

Slash commands:

- `/register action:domme`
  Register a Domme Throne profile for live tracking.
- `/register action:sub`
  Register a Sub sending name so sends can be claimed on the leaderboard.

## Configuration

### 1. Discord IDs

Put your real IDs in [`bot/channels.py`](/Users/patfaint/Documents/Codex/rob-the-bot-components-v2/bot/channels.py).

Example placeholders live in [`bot/channels.example.py`](/Users/patfaint/Documents/Codex/rob-the-bot-components-v2/bot/channels.example.py).

Supported IDs:

- `GUILD_ID`
- `REGISTRATION_CHANNEL_ID`
- `LEADERBOARD_CHANNEL_ID`
- `SEND_TRACK_CHANNEL_ID`
- `EVENT_REPORT_CHANNEL_ID`
- `MODERATION_ROLE_ID`
- `DOMME_ROLE_ID`
- `SUBMISSIVE_ROLE_ID`
- `EVENT_BAN_ROLE_ID`

If `EVENT_REPORT_CHANNEL_ID` is `0` or missing, Rob falls back to `LEADERBOARD_CHANNEL_ID` for final event reports.

### 2. Event Themes and Windows

Edit [`config/events.json`](/Users/patfaint/Documents/Codex/rob-the-bot-components-v2/config/events.json).

Rob loads this file on startup, and `!event reload` will refresh it while the bot is running.

Current committed config includes:

- a default live theme
- a `mothers_day_2026` event stub
- Mother's Day disabled until dates are confirmed

An event only becomes active when:

- `enabled` is `true`
- `start_at` is set
- `end_at` is set
- the current time falls inside that window

If multiple events overlap, Rob logs a warning and uses the first active event in JSON order.

### 3. Environment Variables

See [`.env.example`](/Users/patfaint/Documents/Codex/rob-the-bot-components-v2/.env.example).

Required:

- `DISCORD_TOKEN`

Useful optional values:

- `BOT_NAME`
- `EVENT_NAME`
- `DATABASE_PATH`
- `THRONE_POLL_INTERVAL_SECONDS`
- `THRONE_POLL_PER_DOMME_DELAY_SECONDS`
- `THRONE_HTTP_TIMEOUT_SECONDS`
- `THRONE_USER_AGENT`
- `EVENTS_CONFIG_PATH`

## How Tracking Works

### Live tracking

Live tracking is always on while the bot is online.

- Registered Domme Throne sources are polled continuously.
- New sends are written to the database once.
- Send cards are posted to the send-tracking channel.
- Live leaderboards stay online whether or not an event is active.

### Event tracking

Event tracking is just an extra layer.

- If a send lands during an active configured event window, that send is also tagged with the active `event_key`.
- Event leaderboards only count sends tagged for that active event.
- When the event ends, Rob posts the final report once and returns the leaderboard channel to normal live mode.

### Throne 429 handling

Public Throne page enrichment is handled conservatively.

- Overlay tracking keeps running.
- Page enrichment for that profile is paused for 60 minutes after HTTP 429.
- Rob does not hammer the same rate-limited page every minute.
- Unknown send amounts can still flow through from overlay data when needed.

## Leaderboards

The leaderboard channel shows exactly two auto-updated messages, in this order:

1. Domme Leaderboard
2. Sub Leaderboard

When no event is active, they show live totals.

When an event is active, they switch to the event theme and only count sends recorded during that event window.

## Final Event Reports

When an event ends, Rob posts a final report with:

- event name
- event key
- event window
- total tracked amount
- total send count
- ranked Domme count
- ranked Sub count
- unclaimed total
- final Domme leaderboard
- final Sub leaderboard

The report is posted to `EVENT_REPORT_CHANNEL_ID`, or the leaderboard channel if no separate report channel is configured.

## Project Structure

```text
.
├── .github/workflows/deploy.yml
├── .env.example
├── README.md
├── config/
│   └── events.json
├── install.sh
├── main.py
├── rob-the-bot.service
├── bot/
│   ├── channels.example.py
│   ├── channels.py
│   ├── config.py
│   ├── database.py
│   ├── event_cog.py
│   ├── event_config.py
│   ├── event_views.py
│   ├── throne_scraper.py
│   ├── throne_tracker.py
│   ├── ui/
│   │   ├── cards.py
│   │   ├── components.py
│   │   ├── copy.py
│   │   └── theme.py
│   └── views.py
└── data/
```

## Local Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

Fill in `DISCORD_TOKEN`, set your IDs in `bot/channels.py`, and check `config/events.json` before starting.

## Deploy Workflow

Deploys run from [`.github/workflows/deploy.yml`](/Users/patfaint/Documents/Codex/rob-the-bot-components-v2/.github/workflows/deploy.yml).

The workflow now:

- checks out the repo in GitHub Actions
- syncs the repo contents to `/opt/rob-the-bot/app` over SSH
- preserves `.env`, `.venv`, and `data/` on the server
- installs Python dependencies
- reloads the systemd unit
- restarts `rob-the-bot`

### GitHub Actions secrets you need

Add these in your repo settings:

- `DEPLOY_HOST`
  Your server IP or hostname.
- `DEPLOY_PORT`
  Usually `22`.
- `DEPLOY_USER`
  The deploy user created by `install.sh`. Default: `robdeploy`.
- `DEPLOY_SSH_KEY`
  The private deploy key from the installer output.
- `DEPLOY_KNOWN_HOSTS`
  The `ssh-keyscan -H <server>` line from the installer output.

GitHub path:

`https://github.com/notpatdev/rob-the-bot/settings/secrets/actions`

### What has to exist on the server

The included installer sets this up:

```bash
sudo bash install.sh
```

That gives you:

- `/opt/rob-the-bot/app`
- `/opt/rob-the-bot/data`
- the `robbot` runtime user
- the `robdeploy` SSH deploy user
- the systemd service
- the deploy SSH key and sudo rules needed by the workflow

## Validation

Useful checks:

```bash
python3 -m compileall bot main.py
python3 - <<'PY'
import sys
sys.path.insert(0, ".")
from bot import event_cog, event_views, throne_tracker
print("imports OK")
PY
grep -R "discord.Embed\\|embed=\\|embeds=" -n bot main.py || true
```
