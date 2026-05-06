#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/notpatdev/rob-the-bot.git"
APP_ROOT="/opt/rob-the-bot"
APP_DIR="${APP_ROOT}/app"
DATA_DIR="${APP_ROOT}/data"
SERVICE_NAME="rob-the-bot"
SERVICE_FILE="rob-the-bot.service"
RUNTIME_USER="robbot"
PYTHON_BIN=""

if [[ -t 1 ]]; then
  BOLD="$(printf '\033[1m')"
  BLUE="$(printf '\033[34m')"
  GREEN="$(printf '\033[32m')"
  YELLOW="$(printf '\033[33m')"
  RESET="$(printf '\033[0m')"
else
  BOLD=""
  BLUE=""
  GREEN=""
  YELLOW=""
  RESET=""
fi

banner() {
  echo
  printf '%s%s%s\n' "${BOLD}" "$1" "${RESET}"
}

step() {
  printf '%s[%s]%s %s\n' "${BLUE}" "$1" "${RESET}" "$2"
}

success() {
  printf '%s[done]%s %s\n' "${GREEN}" "${RESET}" "$1"
}

note() {
  printf '%s[note]%s %s\n' "${YELLOW}" "${RESET}" "$1"
}

die() {
  printf '%serror:%s %s\n' "${YELLOW}" "${RESET}" "$1" >&2
  exit 1
}

prompt_int() {
  local label="$1"
  local value=""
  while true; do
    read -r -p "${label}: " value
    if [[ "${value}" =~ ^[0-9]+$ ]]; then
      printf '%s' "${value}"
      return
    fi
    echo "${label} must be a numeric Discord ID."
  done
}

prompt_optional_int() {
  local label="$1"
  local default="${2:-0}"
  local value=""
  while true; do
    read -r -p "${label} [${default}]: " value
    if [[ -z "${value}" ]]; then
      printf '%s' "${default}"
      return
    fi
    if [[ "${value}" =~ ^[0-9]+$ ]]; then
      printf '%s' "${value}"
      return
    fi
    echo "${label} must be a numeric Discord ID."
  done
}

prompt_default() {
  local label="$1"
  local default="$2"
  local value=""
  read -r -p "${label} [${default}]: " value
  if [[ -z "${value}" ]]; then
    printf '%s' "${default}"
  else
    printf '%s' "${value}"
  fi
}

prompt_env_secret() {
  local label="$1"
  local value=""
  while true; do
    read -r -s -p "${label}: " value
    echo
    if [[ -n "${value}" && "${value}" =~ ^[A-Za-z0-9._-]+$ ]]; then
      printf '%s' "${value}"
      return
    fi
    echo "${label} must not contain spaces, quotes, #, or shell metacharacters."
  done
}

write_env_line() {
  local name="$1"
  local value="$2"
  local escaped="${value//\\/\\\\}"
  escaped="${escaped//\"/\\\"}"
  printf '%s="%s"\n' "${name}" "${escaped}"
}

write_channels_py() {
  local guild_id="$1"
  local registration_channel_id="$2"
  local leaderboard_channel_id="$3"
  local send_track_channel_id="$4"
  local domme_role_id="$5"
  local submissive_role_id="$6"
  local moderation_role_id="$7"
  local event_ban_role_id="$8"

  cat > "${APP_DIR}/bot/channels.py" <<EOF
from __future__ import annotations

# ---------------------------------------------------------------------------
# Server-specific IDs
# ---------------------------------------------------------------------------

GUILD_ID = ${guild_id}

# --- Channels ---
WELCOME_CHANNEL_ID = 0
REGISTRATION_CHANNEL_ID = ${registration_channel_id}
VERIFICATION_CHANNEL_ID = REGISTRATION_CHANNEL_ID
VERIFY_LOG_CHANNEL_ID = 0
GENERAL_CHANNEL_ID = 0
ROLES_CHANNEL_ID = 0
INTRODUCTIONS_CHANNEL_ID = 0
LEADERBOARD_CHANNEL_ID = ${leaderboard_channel_id}
SEND_TRACK_CHANNEL_ID = ${send_track_channel_id}

# --- Roles ---
UNVERIFIED_ROLE_ID = 0
VERIFIED_ROLE_ID = 0
DOMME_ROLE_ID = ${domme_role_id}
SUBMISSIVE_ROLE_ID = ${submissive_role_id}
MODERATION_ROLE_ID = ${moderation_role_id}
EVENT_BAN_ROLE_ID = ${event_ban_role_id}
EOF
}

if [[ "${EUID}" -ne 0 || -z "${SUDO_USER:-}" || "${SUDO_USER}" == "root" ]]; then
  die "Run this installer with sudo from your normal deploy user. Example: sudo bash install.sh"
fi

DEPLOY_OWNER="${SUDO_USER}"
DEPLOY_GROUP="$(id -gn "${DEPLOY_OWNER}")"
DEPLOY_HOME="$(getent passwd "${DEPLOY_OWNER}" | cut -d: -f6)"
SERVER_HOSTNAME="$(hostname -f 2>/dev/null || hostname)"

if ! command -v apt-get >/dev/null 2>&1; then
  die "This installer currently supports Debian or Ubuntu systems with apt-get."
fi

banner "Rob server installer"
note "This will install the bot to ${APP_ROOT} and run it as ${RUNTIME_USER}."
note "The deploy user for GitHub Actions will be ${DEPLOY_OWNER}."

step "1/8" "Installing system packages"
apt-get update
apt-get install -y git python3 python3-venv python3-pip software-properties-common

if ! command -v python3.11 >/dev/null 2>&1; then
  if [[ -r /etc/os-release ]]; then
    # shellcheck source=/dev/null
    . /etc/os-release
    if [[ "${ID:-}" == "ubuntu" ]]; then
      add-apt-repository -y ppa:deadsnakes/ppa
      apt-get update
    fi
  fi
fi

apt-get install -y python3.11 python3.11-venv
PYTHON_BIN="$(command -v python3.11)"

if ! "${PYTHON_BIN}" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
then
  die "Python 3.11 or newer is required."
fi
success "System packages installed"

step "2/8" "Creating runtime user and directories"
if ! getent group "${RUNTIME_USER}" >/dev/null 2>&1; then
  groupadd --system "${RUNTIME_USER}"
fi

if ! id "${RUNTIME_USER}" >/dev/null 2>&1; then
  useradd --system --gid "${RUNTIME_USER}" --home-dir "${APP_ROOT}" --shell /usr/sbin/nologin "${RUNTIME_USER}"
fi

mkdir -p "${APP_DIR}" "${DATA_DIR}"
success "Runtime user and directories ready"

step "3/8" "Fetching repository"
if [[ -d "${APP_DIR}/.git" ]]; then
  git -C "${APP_DIR}" remote set-url origin "${REPO_URL}"
  git -C "${APP_DIR}" fetch origin main
  git -C "${APP_DIR}" switch main
  git -C "${APP_DIR}" pull --ff-only origin main
else
  rm -rf "${APP_DIR}"
  git clone "${REPO_URL}" "${APP_DIR}"
fi
success "Repository ready at ${APP_DIR}"

step "4/8" "Creating virtual environment"
"${PYTHON_BIN}" -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"
success "Python environment ready"

banner "Discord configuration"
note "You'll enter the IDs Rob needs for the event tracker."

DISCORD_TOKEN="$(prompt_env_secret "DISCORD_TOKEN")"
BOT_NAME="$(prompt_default "BOT_NAME" "Rob")"
EVENT_NAME="$(prompt_default "EVENT_NAME" "Mother's Day Event")"
GUILD_ID="$(prompt_int "GUILD_ID")"
REGISTRATION_CHANNEL_ID="$(prompt_int "REGISTRATION_CHANNEL_ID")"
LEADERBOARD_CHANNEL_ID="$(prompt_int "LEADERBOARD_CHANNEL_ID")"
SEND_TRACK_CHANNEL_ID="$(prompt_int "SEND_TRACK_CHANNEL_ID")"
DOMME_ROLE_ID="$(prompt_int "DOMME_ROLE_ID")"
SUBMISSIVE_ROLE_ID="$(prompt_int "SUBMISSIVE_ROLE_ID")"
MODERATION_ROLE_ID="$(prompt_int "MODERATION_ROLE_ID")"
EVENT_BAN_ROLE_ID="$(prompt_optional_int "EVENT_BAN_ROLE_ID" "0")"

step "5/8" "Writing environment and channel configuration"
{
  write_env_line "DISCORD_TOKEN" "${DISCORD_TOKEN}"
  write_env_line "BOT_NAME" "${BOT_NAME}"
  write_env_line "EVENT_NAME" "${EVENT_NAME}"
  write_env_line "DATABASE_PATH" "${DATA_DIR}/rob_the_bot.sqlite3"
  write_env_line "THRONE_POLL_INTERVAL_SECONDS" "60"
} > "${APP_DIR}/.env"

write_channels_py \
  "${GUILD_ID}" \
  "${REGISTRATION_CHANNEL_ID}" \
  "${LEADERBOARD_CHANNEL_ID}" \
  "${SEND_TRACK_CHANNEL_ID}" \
  "${DOMME_ROLE_ID}" \
  "${SUBMISSIVE_ROLE_ID}" \
  "${MODERATION_ROLE_ID}" \
  "${EVENT_BAN_ROLE_ID}"

chmod 600 "${APP_DIR}/.env"
chown -R "${RUNTIME_USER}:${RUNTIME_USER}" "${DATA_DIR}"
chown -R "${DEPLOY_OWNER}:${DEPLOY_GROUP}" "${APP_DIR}"
chown "${RUNTIME_USER}:${RUNTIME_USER}" "${APP_DIR}/.env"
success "Configuration written"

step "6/8" "Installing systemd service"
install -m 0644 "${APP_DIR}/${SERVICE_FILE}" "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}"
success "Service installed and started"

step "7/8" "Running quick health check"
systemctl --no-pager --full status "${SERVICE_NAME}" >/dev/null
success "systemd reports ${SERVICE_NAME} is available"

step "8/8" "Final setup notes"
echo
printf '%sInstall complete.%s\n' "${GREEN}" "${RESET}"
echo
printf '%sRob service commands%s\n' "${BOLD}" "${RESET}"
echo "  sudo systemctl status ${SERVICE_NAME}"
echo "  sudo systemctl restart ${SERVICE_NAME}"
echo "  sudo journalctl -u ${SERVICE_NAME} -f"
echo
printf '%sWhat was written%s\n' "${BOLD}" "${RESET}"
echo "  App directory: ${APP_DIR}"
echo "  Database: ${DATA_DIR}/rob_the_bot.sqlite3"
echo "  Environment file: ${APP_DIR}/.env"
echo "  Channel config: ${APP_DIR}/bot/channels.py"
echo
printf '%sGitHub Actions updater setup%s\n' "${BOLD}" "${RESET}"
echo "  Repository: notpatdev/rob-the-bot"
echo "  Branch: main"
echo "  Deploy path on server: ${APP_DIR}"
echo "  Service name: ${SERVICE_NAME}"
echo "  Detected server hostname: ${SERVER_HOSTNAME}"
echo "  DEPLOY_HOST=<public IP or DNS for this server>"
echo "  DEPLOY_USER=${DEPLOY_OWNER}"
echo "  DEPLOY_PORT=22"
echo "  DEPLOY_SSH_KEY=<paste the private key contents>"
echo "  DEPLOY_KNOWN_HOSTS=<paste the ssh-keyscan output>"
echo
printf '%sRun these on your local machine%s\n' "${BOLD}" "${RESET}"
echo "  ssh-keygen -t ed25519 -C \"github-actions-deploy\" -f ~/.ssh/rob-the-bot-deploy"
echo "  cat ~/.ssh/rob-the-bot-deploy.pub"
echo "  cat ~/.ssh/rob-the-bot-deploy"
echo "  ssh-keyscan -H YOUR_SERVER_IP_OR_DNS"
echo
printf '%sAdd the public key here on the server%s\n' "${BOLD}" "${RESET}"
echo "  ${DEPLOY_HOME}/.ssh/authorized_keys"
echo
note "The bot logs to journald now, so journalctl is the only log view you need."
