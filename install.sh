#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/notpatdev/rob-the-bot.git"
APP_ROOT="/opt/rob-the-bot"
APP_DIR="${APP_ROOT}/app"
DATA_DIR="${APP_ROOT}/data"
SERVICE_NAME="rob-the-bot"
SERVICE_FILE="rob-the-bot.service"
RUNTIME_USER="robbot"
DEPLOY_USER="robdeploy"
DEPLOY_GROUP=""
PYTHON_BIN=""
DEPLOY_HOME=""
DEPLOY_HOST=""
DEPLOY_PORT="22"
DEPLOY_PUBLIC_KEY=""
DEPLOY_KNOWN_HOSTS=""
INSTALL_BIN="$(command -v install)"
SYSTEMCTL_BIN="$(command -v systemctl)"

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

prompt_port() {
  local label="$1"
  local default="$2"
  local value=""
  while true; do
    read -r -p "${label} [${default}]: " value
    if [[ -z "${value}" ]]; then
      printf '%s' "${default}"
      return
    fi
    if [[ "${value}" =~ ^[0-9]+$ ]] && (( value >= 1 && value <= 65535 )); then
      printf '%s' "${value}"
      return
    fi
    echo "${label} must be a valid TCP port."
  done
}

prompt_public_key() {
  local label="$1"
  local value=""
  while true; do
    read -r -p "${label} (leave blank to skip): " value
    if [[ -z "${value}" ]]; then
      printf '%s' ""
      return
    fi
    if [[ "${value}" =~ ^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256)\ [A-Za-z0-9+/=]+([[:space:]].*)?$ ]]; then
      printf '%s' "${value}"
      return
    fi
    echo "That does not look like a valid SSH public key."
  done
}

write_env_line() {
  local name="$1"
  local value="$2"
  local escaped="${value//\\/\\\\}"
  escaped="${escaped//\"/\\\"}"
  printf '%s="%s"\n' "${name}" "${escaped}"
}

run_as_deploy_user() {
  runuser -u "${DEPLOY_USER}" -- "$@"
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

REGISTRATION_CHANNEL_ID = ${registration_channel_id}
LEADERBOARD_CHANNEL_ID = ${leaderboard_channel_id}
SEND_TRACK_CHANNEL_ID = ${send_track_channel_id}

DOMME_ROLE_ID = ${domme_role_id}
SUBMISSIVE_ROLE_ID = ${submissive_role_id}
MODERATION_ROLE_ID = ${moderation_role_id}
EVENT_BAN_ROLE_ID = ${event_ban_role_id}
EOF
}

if [[ "${EUID}" -ne 0 || -z "${SUDO_USER:-}" || "${SUDO_USER}" == "root" ]]; then
  die "Run this installer with sudo from your normal admin user. Example: sudo bash install.sh"
fi

SERVER_HOSTNAME="$(hostname -f 2>/dev/null || hostname)"
DEFAULT_PUBLIC_HOST="$(hostname -I 2>/dev/null | awk '{print $1}')"
if [[ -z "${DEFAULT_PUBLIC_HOST}" ]]; then
  DEFAULT_PUBLIC_HOST="${SERVER_HOSTNAME}"
fi

if ! command -v apt-get >/dev/null 2>&1; then
  die "This installer currently supports Debian or Ubuntu systems with apt-get."
fi

banner "Rob server installer"
note "This will install the bot to ${APP_ROOT} and run it as ${RUNTIME_USER}."
note "A dedicated deploy user (${DEPLOY_USER}) will be created for GitHub Actions."

step "1/10" "Installing system packages"
apt-get update
apt-get install -y git python3 python3-venv python3-pip software-properties-common openssh-client

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

step "2/10" "Creating runtime and deploy users"
if ! getent group "${RUNTIME_USER}" >/dev/null 2>&1; then
  groupadd --system "${RUNTIME_USER}"
fi

if ! id "${RUNTIME_USER}" >/dev/null 2>&1; then
  useradd --system --gid "${RUNTIME_USER}" --home-dir "${APP_ROOT}" --shell /usr/sbin/nologin "${RUNTIME_USER}"
fi

if ! id "${DEPLOY_USER}" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "${DEPLOY_USER}"
fi

DEPLOY_HOME="$(getent passwd "${DEPLOY_USER}" | cut -d: -f6)"
DEPLOY_GROUP="$(id -gn "${DEPLOY_USER}")"
mkdir -p "${APP_ROOT}" "${DATA_DIR}"
chown "${DEPLOY_USER}:${DEPLOY_GROUP}" "${APP_ROOT}"
chown "${RUNTIME_USER}:${RUNTIME_USER}" "${DATA_DIR}"
chmod 755 "${APP_ROOT}" "${DATA_DIR}"
success "Users and directories ready"

step "3/10" "Fetching repository"
if [[ -d "${APP_DIR}/.git" ]]; then
  chown -R "${DEPLOY_USER}:${DEPLOY_GROUP}" "${APP_DIR}"
  run_as_deploy_user git -C "${APP_DIR}" remote set-url origin "${REPO_URL}"
  run_as_deploy_user git -C "${APP_DIR}" fetch origin main
  run_as_deploy_user git -C "${APP_DIR}" switch main
  run_as_deploy_user git -C "${APP_DIR}" pull --ff-only origin main
else
  rm -rf "${APP_DIR}"
  run_as_deploy_user git clone "${REPO_URL}" "${APP_DIR}"
fi
success "Repository ready at ${APP_DIR}"

step "4/10" "Creating virtual environment"
chown -R "${DEPLOY_USER}:${DEPLOY_GROUP}" "${APP_DIR}"
run_as_deploy_user "${PYTHON_BIN}" -m venv "${APP_DIR}/.venv"
run_as_deploy_user "${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip
run_as_deploy_user "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"
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

banner "GitHub deploy configuration"
note "Paste the public key from your local machine if you want GitHub Actions SSH ready now."
DEPLOY_HOST="$(prompt_default "Public server IP or DNS for GitHub Actions" "${DEFAULT_PUBLIC_HOST}")"
DEPLOY_PORT="$(prompt_port "SSH port for GitHub Actions" "22")"
DEPLOY_PUBLIC_KEY="$(prompt_public_key "GitHub Actions deploy public key")"
if [[ -n "${DEPLOY_HOST}" ]]; then
  DEPLOY_KNOWN_HOSTS="$(ssh-keyscan -H -p "${DEPLOY_PORT}" "${DEPLOY_HOST}" 2>/dev/null || true)"
fi

step "5/10" "Writing environment and channel configuration"
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
chown -R "${DEPLOY_USER}:${DEPLOY_GROUP}" "${APP_DIR}"
chown "${RUNTIME_USER}:${RUNTIME_USER}" "${APP_DIR}/.env"
success "Configuration written"

step "6/10" "Configuring SSH deploy access"
install -d -m 700 -o "${DEPLOY_USER}" -g "${DEPLOY_GROUP}" "${DEPLOY_HOME}/.ssh"
touch "${DEPLOY_HOME}/.ssh/authorized_keys"
chown "${DEPLOY_USER}:${DEPLOY_GROUP}" "${DEPLOY_HOME}/.ssh/authorized_keys"
chmod 600 "${DEPLOY_HOME}/.ssh/authorized_keys"

if [[ -n "${DEPLOY_PUBLIC_KEY}" ]]; then
  if ! grep -Fxq "${DEPLOY_PUBLIC_KEY}" "${DEPLOY_HOME}/.ssh/authorized_keys"; then
    printf '%s\n' "${DEPLOY_PUBLIC_KEY}" >> "${DEPLOY_HOME}/.ssh/authorized_keys"
  fi
  success "Deploy public key installed for ${DEPLOY_USER}"
else
  note "Skipped public key install. You can add one later to ${DEPLOY_HOME}/.ssh/authorized_keys"
fi

cat > "/etc/sudoers.d/${SERVICE_NAME}-deploy" <<EOF
${DEPLOY_USER} ALL=(root) NOPASSWD: ${SYSTEMCTL_BIN} stop ${SERVICE_NAME}, ${SYSTEMCTL_BIN} start ${SERVICE_NAME}, ${SYSTEMCTL_BIN} restart ${SERVICE_NAME}, ${SYSTEMCTL_BIN} status ${SERVICE_NAME}, ${SYSTEMCTL_BIN} daemon-reload, ${INSTALL_BIN} -m 0644 ${APP_DIR}/${SERVICE_FILE} /etc/systemd/system/${SERVICE_NAME}.service
EOF
chmod 440 "/etc/sudoers.d/${SERVICE_NAME}-deploy"
visudo -cf "/etc/sudoers.d/${SERVICE_NAME}-deploy" >/dev/null
success "Deploy user sudo rules configured"

step "7/10" "Installing systemd service"
install -m 0644 "${APP_DIR}/${SERVICE_FILE}" "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}"
success "Service installed and started"

step "8/10" "Running quick health check"
systemctl --no-pager --full status "${SERVICE_NAME}" >/dev/null
success "systemd reports ${SERVICE_NAME} is available"

step "9/10" "Checking deploy known_hosts"
if [[ -n "${DEPLOY_KNOWN_HOSTS}" ]]; then
  success "Collected known_hosts entry for ${DEPLOY_HOST}:${DEPLOY_PORT}"
else
  note "Could not collect known_hosts automatically. The final summary includes the command to generate it."
fi

step "10/10" "Final setup notes"
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
echo "  Deploy user: ${DEPLOY_USER}"
echo "  Deploy key file on server: ${DEPLOY_HOME}/.ssh/authorized_keys"
echo
printf '%sGitHub Actions updater setup%s\n' "${BOLD}" "${RESET}"
echo "  Repository: notpatdev/rob-the-bot"
echo "  Branch: main"
echo "  Deploy path on server: ${APP_DIR}"
echo "  Service name: ${SERVICE_NAME}"
echo "  Detected server hostname: ${SERVER_HOSTNAME}"
echo
printf '%sCopy these into GitHub Secrets%s\n' "${BOLD}" "${RESET}"
echo "  DEPLOY_HOST=${DEPLOY_HOST}"
echo "  DEPLOY_USER=${DEPLOY_USER}"
echo "  DEPLOY_PORT=${DEPLOY_PORT}"
echo "  DEPLOY_SSH_KEY=<paste the private key contents from your local machine>"
if [[ -n "${DEPLOY_KNOWN_HOSTS}" ]]; then
  echo "  DEPLOY_KNOWN_HOSTS="
  printf '%s\n' "${DEPLOY_KNOWN_HOSTS}"
else
  echo "  DEPLOY_KNOWN_HOSTS=<run ssh-keyscan and paste the output>"
fi
echo
printf '%sRun these on your local machine%s\n' "${BOLD}" "${RESET}"
echo "  ssh-keygen -t ed25519 -C \"github-actions-deploy\" -f ~/.ssh/rob-the-bot-deploy"
echo "  cat ~/.ssh/rob-the-bot-deploy.pub"
echo "  cat ~/.ssh/rob-the-bot-deploy"
echo "  ssh-keyscan -H -p ${DEPLOY_PORT} ${DEPLOY_HOST}"
echo
printf '%sWhat goes where%s\n' "${BOLD}" "${RESET}"
echo "  Public key (.pub line): ${DEPLOY_HOME}/.ssh/authorized_keys on the server"
echo "  Private key: GitHub secret named DEPLOY_SSH_KEY"
echo "  known_hosts output: GitHub secret named DEPLOY_KNOWN_HOSTS"
echo
note "The bot logs to journald now, so journalctl is the only log view you need."
