#!/usr/bin/env bash
#
# Deploy the Tesla Energy Dashboard to the Raspberry Pi.
#
# Run from your Mac, from the project root:  ./deploy/deploy.sh
# You will be prompted for the Pi's SSH password (and its sudo password once,
# for the systemd step). Nothing secret is committed to git; .env and the
# token database are copied directly from this machine to the Pi.
#
set -euo pipefail

PI_HOST="${PI_HOST:-pi@raspberrypi.local}"              # set for your own Pi
APP_DIR="${APP_DIR:-/home/pi/tesla-energy-dashboard}"  # must match the .service file
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Syncing code to ${PI_HOST}:${APP_DIR}"
rsync -az --delete \
  --exclude '.git' --exclude '.venv' --exclude '__pycache__' \
  --exclude '*.pyc' --exclude '*.egg-info' --exclude '.pytest_cache' \
  --exclude 'energy.sqlite3' --exclude '.env' \
  "${HERE}/" "${PI_HOST}:${APP_DIR}/"

echo "==> Copying .env and seeding OAuth tokens (energy.sqlite3)"
scp "${HERE}/.env" "${PI_HOST}:${APP_DIR}/.env"
if [ -f "${HERE}/energy.sqlite3" ]; then
  scp "${HERE}/energy.sqlite3" "${PI_HOST}:${APP_DIR}/energy.sqlite3"
fi

# 600s (10 min) keeps request volume inside Tesla's $10/mo free API credit.
# Shorter intervals cost ~$0.002 per poll; 60s would run ~$75+/mo.
echo "==> Enabling the background sampler in the Pi's .env (600s)"
ssh "${PI_HOST}" "cd '${APP_DIR}' && \
  if grep -q '^SAMPLE_INTERVAL_SECONDS=' .env; then \
    sed -i 's/^SAMPLE_INTERVAL_SECONDS=.*/SAMPLE_INTERVAL_SECONDS=600/' .env; \
  else echo 'SAMPLE_INTERVAL_SECONDS=600' >> .env; fi"

echo "==> Creating venv and installing (uses piwheels; first run is slow)"
ssh "${PI_HOST}" "cd '${APP_DIR}' && \
  python3 -m venv .venv && \
  .venv/bin/python -m pip install --upgrade pip && \
  .venv/bin/python -m pip install -e ."

echo "==> Installing + starting the systemd service (needs sudo)"
ssh -t "${PI_HOST}" "sudo cp '${APP_DIR}/deploy/tesla-energy-dashboard.service' /etc/systemd/system/ && \
  sudo systemctl daemon-reload && \
  sudo systemctl enable --now tesla-energy-dashboard.service && \
  sleep 2 && sudo systemctl status tesla-energy-dashboard.service --no-pager | head -14"

echo ""
echo "==> Done. Dashboard: http://${PI_HOST#*@}:8000"
echo "    Logs:  ssh ${PI_HOST} 'journalctl -u tesla-energy-dashboard -f'"
