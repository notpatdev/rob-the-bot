# The Butler

The Butler is a production-ready Discord bot for The Drain Server. It handles welcomes, 18+ age verification, staff approval, role assignment, SQLite persistence, a restricted help menu, and Domme profile setup.

## Features

- Welcome embed when a member joins
- Automatic Unverified role assignment on join
- Persistent age verification panel
- DM-based verification flow with one edited setup embed
- Staff approval and denial buttons restricted to `MODERATION_ROLE_ID`
- Duplicate pending-request protection in SQLite
- Public plain-text welcome after approval
- Restricted `/help` command with paginated embeds
- Domme profile setup, display, and deletion
- Production `install.sh` bootstrap script
- Hardened `the-butler.service` systemd unit
- GitHub Actions deployment workflow

## Project Structure

```text
.
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── install.sh
├── main.py
├── the-butler.service
├── bot/
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   ├── embeds.py
│   ├── messages.py
│   ├── views.py
│   ├── verification.py
│   └── utils.py
├── data/
│   └── .gitkeep
└── .github/
    └── workflows/
        └── deploy.yml
```

## Discord Developer Portal Setup

1. Create an application in the Discord Developer Portal.
2. Add a bot to the application.
3. Copy the bot token and store it only in your local `.env` or on the server.
4. Enable these privileged gateway intents:
   - `MESSAGE CONTENT`
   - `MEMBERS`
5. Invite the bot with these permissions:
   - View Channels
   - Send Messages
   - Embed Links
   - Attach Files
   - Read Message History
   - Use Slash Commands
   - Manage Roles

The bot role must sit above the Unverified, Verified, Domme, and Submissive roles in Discord role order.

## Server Setup

Create these channels before starting the bot:

- Welcome channel
- Verification channel
- Verification log channel
- General channel
- Roles channel
- Introductions channel

Create these roles before starting the bot:

- Unverified
- Verified
- Domme
- Submissive
- Moderation

Copy the channel and role IDs into `.env`.

## Local Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

Edit `.env` before starting the bot.

`GUILD_ID` is optional but useful while testing because it syncs `/help` to one server immediately.

## Environment Variables

```env
DISCORD_TOKEN=
GUILD_ID=
WELCOME_CHANNEL_ID=
VERIFICATION_CHANNEL_ID=
VERIFY_LOG_CHANNEL_ID=
GENERAL_CHANNEL_ID=
ROLES_CHANNEL_ID=
INTRODUCTIONS_CHANNEL_ID=
UNVERIFIED_ROLE_ID=
VERIFIED_ROLE_ID=
DOMME_ROLE_ID=
SUBMISSIVE_ROLE_ID=
MODERATION_ROLE_ID=
DATABASE_PATH=data/the_butler.sqlite3
```

Never commit `.env`. The token belongs only on your machine or server.

## Commands

Prefix commands:

- `!setup_verification`
  Posts the verification panel in the configured verification channel.
- `!verify_status <user>`
  Checks a user's verification status.
- `!verify_cleanup`
  Shows users who still have the Unverified role.
- `!resync [guild|clear|global]`
  Dev/admin command to re-sync slash commands and clean up duplicate registrations.
- `!domme`
  Shows your saved Domme profile publicly, or starts profile setup via DM if you don't have one.
- `!domme @mention`
  Shows the mentioned member's Domme profile publicly.
- `!domme delete`
  Deletes the saved Domme profile after confirmation.

`!setup_verification`, `!verify_status`, `!verify_cleanup`, and `!resync` require `MODERATION_ROLE_ID` or Administrator.

Slash commands:

- `/help`
  Shows the restricted bot help menu.
- `/reaction_role_setup`
  Moderator-only setup form for creating reaction-role embeds and emoji-to-role mappings.
- `/domme`
  Shows your saved Domme profile publicly in the channel, or starts profile setup via DM if you don't have one.
- `/domme user:@Someone`
  Shows another member's Domme profile publicly in the channel.
- `/domme action:delete`
  Deletes the saved Domme profile after confirmation.

`/help` only works for these Discord user IDs:

- `1493691258873319454`
- `1299308718009356289`

## Verification Flow

1. Member joins and receives the Unverified role.
2. The verification panel button starts a DM flow.
3. The bot edits one DM embed through:
   - verification input
   - role selection
4. The bot stores the request in SQLite and posts it to the verification log channel.
5. Only members with `MODERATION_ROLE_ID` can approve or deny the request.
6. Approval removes Unverified, adds Verified, adds the selected role, DMs the user, and posts the public plain-text welcome line.

Users cannot start verification again if they already have the Verified role, and duplicate pending requests are blocked in SQLite.

## Domme Profile Setup

Run `/domme` or `!domme` in a server channel as a member with `DOMME_ROLE_ID`.

If no profile exists, The Butler replies in-channel and starts a DM setup flow. The DM uses one edited message across the setup steps:

1. Intro
2. Name and honorific
3. Nitty gritty details
4. Payment methods
5. Optional Throne tracking step if a Throne link was provided
6. Coffee feature
7. Final review

Saved profiles live in the `domme_profiles` SQLite table.

## Production Install

Run the installer on a fresh Linux server:

```bash
sudo bash install.sh
```

Run it from the deploy user's shell with `sudo`, not from a direct root login.

The installer:

- Installs `git`, `python3`, `python3-venv`, `python3-pip`, and Python 3.11
- Creates the `butlerbot` runtime user
- Creates `/opt/the-butler/app`, `/opt/the-butler/data`, and `/opt/the-butler/logs`
- Clones this repository
- Creates a virtual environment
- Installs dependencies
- Prompts for the Discord token, channel IDs, and role IDs with numeric ID validation
- Writes `/opt/the-butler/app/.env`
- Sets `chmod 600` on `.env`
- Stores the production SQLite database at `/opt/the-butler/data/the_butler.sqlite3`
- Installs and starts `the-butler.service`

Useful commands after install:

```bash
sudo systemctl status the-butler
sudo journalctl -u the-butler -f
sudo systemctl restart the-butler
```

## GitHub Deployment Setup

The workflow in `.github/workflows/deploy.yml` deploys automatically on pushes to `main`.

Add these repository secrets in GitHub:

- `DEPLOY_HOST` -> Server IP
- `DEPLOY_USER` -> `butlerdeploy`
- `DEPLOY_PORT` -> `22`
- `DEPLOY_SSH_KEY` -> private SSH key
- `DEPLOY_KNOWN_HOSTS` -> pinned `known_hosts` entry for the server

Generate a deploy key pair on a trusted machine:

```bash
ssh-keygen -t ed25519 -C "butler deploy" -f ~/.ssh/the-butler-deploy
```

Paste the public key onto the server for the deploy user:

```bash
mkdir -p ~/.ssh
cat ~/.ssh/the-butler-deploy.pub >> ~/.ssh/authorized_keys
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
```

Paste the private key contents into the GitHub `DEPLOY_SSH_KEY` secret.

Create the pinned host entry from a trusted machine and save it as `DEPLOY_KNOWN_HOSTS`:

```bash
ssh-keyscan -p 22 your-server.example.com
```

The deploy user should be separate from `butlerbot`. The runtime bot token is not stored in GitHub. It remains in `/opt/the-butler/app/.env` on the server.

## Systemd Security

The Butler runs as `butlerbot`, not root. The service uses privilege restrictions and only allows writes to:

- `/opt/the-butler/data`
- `/opt/the-butler/logs`

Keep the runtime user separate from the deploy user. The deploy user updates `/opt/the-butler/app`, installs dependencies, refreshes the service file, reloads systemd, and restarts the bot through `sudo`.

## Troubleshooting

`/help` is missing:

- Confirm the bot is online.
- Set `GUILD_ID` for immediate guild sync while testing.
- Reinvite the bot with `applications.commands`.

Prefix commands do not respond:

- Confirm `MESSAGE CONTENT` intent is enabled.
- Confirm the command prefix is `!`.
- Check the service logs for startup errors.

The bot cannot assign roles:

- Move the bot role above every role it manages.
- Confirm `Manage Roles` is enabled.
- Check the configured role IDs.

Users cannot start verification:

- Ask them to enable DMs from server members.
- Confirm `MESSAGE CONTENT` and `MEMBERS` intents are enabled.
- Confirm they do not already have the Verified role.

Staff buttons do not work after restart:

- Confirm pending requests exist in `/opt/the-butler/data/the_butler.sqlite3`.
- Check the service logs for startup or database errors.

Check logs:

```bash
sudo journalctl -u the-butler -f
```
