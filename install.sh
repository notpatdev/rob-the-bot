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

if [[ "${EUID}" -ne 0 || -z "${SUDO_USER:-}" || "${SUDO_USER}" == "root" ]]; then
  die "Run this installer with sudo from your normal admin user. Example: sudo bash install.sh"
fi

if ! command -v apt-get >/dev/null 2>&1; then
  die "This installer currently supports Debian or Ubuntu systems with apt-get."
fi

banner "Rob server installer"
note "This will install the bot to ${APP_ROOT} and run it as ${RUNTIME_USER}."
note "After install, use !import ids inside Discord to set your channel/role IDs."

step "1/7" "Installing system packages"
apt-get update -q
apt-get install -y git python3 python3-venv python3-pip software-properties-common

if ! command -v python3.11 >/dev/null 2>&1; then
  if [[ -r /etc/os-release ]]; then
    # shellcheck source=/dev/null
    . /etc/os-release
    if [[ "${ID:-}" == "ubuntu" ]]; then
      add-apt-repository -y ppa:deadsnakes/ppa
      apt-get update -q
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

step "2/7" "Creating runtime and deploy users"
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

step "3/7" "Fetching repository"
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

step "4/7" "Creating virtual environment"
chown -R "${DEPLOY_USER}:${DEPLOY_GROUP}" "${APP_DIR}"
run_as_deploy_user "${PYTHON_BIN}" -m venv "${APP_DIR}/.venv"
run_as_deploy_user "${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip -q
run_as_deploy_user "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt" -q
success "Python environment ready"

banner "Bot configuration"
note "Just the token — set channel/role IDs later with !import ids in Discord."

DISCORD_TOKEN="$(prompt_env_secret "DISCORD_TOKEN")"
BOT_NAME="$(prompt_default "BOT_NAME" "Rob")"
EVENT_NAME="$(prompt_default "EVENT_NAME" "Event")"

step "5/7" "Writing environment file"
{
  write_env_line "DISCORD_TOKEN" "${DISCORD_TOKEN}"
  write_env_line "BOT_NAME" "${BOT_NAME}"
  write_env_line "EVENT_NAME" "${EVENT_NAME}"
  write_env_line "DATABASE_PATH" "${DATA_DIR}/rob_the_bot.sqlite3"
  write_env_line "THRONE_POLL_INTERVAL_SECONDS" "60"
} > "${APP_DIR}/.env"

chmod 600 "${APP_DIR}/.env"
chown "${RUNTIME_USER}:${RUNTIME_USER}" "${APP_DIR}/.env"
chown -R "${DEPLOY_USER}:${DEPLOY_GROUP}" "${APP_DIR}"
chown -R "${RUNTIME_USER}:${RUNTIME_USER}" "${DATA_DIR}"
success "Environment file written"

step "6/7" "Configuring deploy user sudo access"
install -d -m 700 -o "${DEPLOY_USER}" -g "${DEPLOY_GROUP}" "${DEPLOY_HOME}/.ssh"
touch "${DEPLOY_HOME}/.ssh/authorized_keys"
chown "${DEPLOY_USER}:${DEPLOY_GROUP}" "${DEPLOY_HOME}/.ssh/authorized_keys"
chmod 600 "${DEPLOY_HOME}/.ssh/authorized_keys"

cat > "/etc/sudoers.d/${SERVICE_NAME}-deploy" <<EOF
${DEPLOY_USER} ALL=(root) NOPASSWD: ${SYSTEMCTL_BIN} stop ${SERVICE_NAME}, ${SYSTEMCTL_BIN} start ${SERVICE_NAME}, ${SYSTEMCTL_BIN} restart ${SERVICE_NAME}, ${SYSTEMCTL_BIN} status ${SERVICE_NAME}, ${SYSTEMCTL_BIN} daemon-reload
EOF
chmod 440 "/etc/sudoers.d/${SERVICE_NAME}-deploy"
visudo -cf "/etc/sudoers.d/${SERVICE_NAME}-deploy" >/dev/null
success "Deploy user ready (add SSH keys to ${DEPLOY_HOME}/.ssh/authorized_keys if needed)"

step "7/7" "Installing and starting systemd service"
install -m 0644 "${APP_DIR}/${SERVICE_FILE}" "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}"
success "Service installed and started"

echo
printf '%sInstall complete!%s\n' "${GREEN}" "${RESET}"
echo
printf '%sService commands%s\n' "${BOLD}" "${RESET}"
echo "  sudo systemctl status ${SERVICE_NAME}"
echo "  sudo systemctl restart ${SERVICE_NAME}"
echo "  sudo journalctl -u ${SERVICE_NAME} -f"
echo
printf '%sNext steps%s\n' "${BOLD}" "${RESET}"
echo "  1. In Discord, run:  !import ids"
echo "     The bot will open a form — paste your server's channel and role IDs."
echo "  2. Restart the bot after saving:  sudo systemctl restart ${SERVICE_NAME}"
echo
printf '%sDeploy updates via curl%s\n' "${BOLD}" "${RESET}"
echo "  curl -fsSL https://raw.githubusercontent.com/notpatdev/rob-the-bot/main/deploy.sh | sudo -u ${DEPLOY_USER} bash"
echo
note "The bot logs to journald — use journalctl to view them."
