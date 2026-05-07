#!/usr/bin/env bash
# deploy.sh — update Rob to the latest version.
#
# Run as the deploy user (robdeploy):
#   curl -fsSL https://raw.githubusercontent.com/notpatdev/rob-the-bot/main/deploy.sh | bash
#
# Or with sudo when logged in as an admin:
#   curl -fsSL https://raw.githubusercontent.com/notpatdev/rob-the-bot/main/deploy.sh | sudo -u robdeploy bash
set -euo pipefail

APP_ROOT="/opt/rob-the-bot"
APP_DIR="${APP_ROOT}/app"
SERVICE_NAME="rob-the-bot"

if [[ -t 1 ]]; then
  GREEN="$(printf '\033[32m')"
  BLUE="$(printf '\033[34m')"
  YELLOW="$(printf '\033[33m')"
  BOLD="$(printf '\033[1m')"
  RESET="$(printf '\033[0m')"
else
  GREEN=""
  BLUE=""
  YELLOW=""
  BOLD=""
  RESET=""
fi

step() { printf '%s[deploy]%s %s\n' "${BLUE}" "${RESET}" "$1"; }
ok()   { printf '%s[ok]%s %s\n' "${GREEN}" "${RESET}" "$1"; }
note() { printf '%s[note]%s %s\n' "${YELLOW}" "${RESET}" "$1"; }

if [[ ! -d "${APP_DIR}/.git" ]]; then
  printf 'error: %s is not a git repository. Run install.sh first.\n' "${APP_DIR}" >&2
  exit 1
fi

step "Pulling latest code from main..."
git -C "${APP_DIR}" fetch origin main
git -C "${APP_DIR}" reset --hard origin/main
ok "Code updated to $(git -C "${APP_DIR}" rev-parse --short HEAD)"

step "Upgrading Python dependencies..."
"${APP_DIR}/.venv/bin/pip" install --upgrade pip -qq
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt" -qq
ok "Dependencies up to date"

step "Restarting ${SERVICE_NAME} service..."
sudo systemctl restart "${SERVICE_NAME}"
ok "Service restarted"

echo
printf '%sDeploy complete!%s  ' "${BOLD}" "${RESET}"
git -C "${APP_DIR}" log -1 --pretty=format:'%h %s' 2>/dev/null || true
echo
note "Check logs: sudo journalctl -u ${SERVICE_NAME} -f"
