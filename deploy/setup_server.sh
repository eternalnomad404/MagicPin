#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu 24.04 EC2 box. Run as the default 'ubuntu' user:
#   bash deploy/setup_server.sh <public-ip>
# Installs Python deps, a systemd service for the bot, and Caddy for HTTPS on
# https://<ip-with-dashes>.sslip.io (no domain purchase, no DNS setup).
set -euo pipefail

PUBLIC_IP="${1:?usage: setup_server.sh <public-ip>}"
HOST="$(echo "$PUBLIC_IP" | tr . -).sslip.io"
APP_DIR="/opt/nukkad"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> host will be https://$HOST"

sudo apt-get update -y
sudo apt-get install -y rsync python3 python3-venv python3-pip debian-keyring debian-archive-keyring apt-transport-https curl

# ---- app ----
sudo mkdir -p "$APP_DIR"
sudo rsync -a --delete --exclude '.git' --exclude '.env' --exclude 'logs' --exclude 'expanded' --exclude 'aws-key' \
  "$REPO_DIR/" "$APP_DIR/"
sudo chown -R ubuntu:ubuntu "$APP_DIR"
cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
mkdir -p logs

if [ ! -f "$APP_DIR/.env" ]; then
  echo "!! $APP_DIR/.env is missing. Copy it with: scp .env ubuntu@$PUBLIC_IP:$APP_DIR/.env  then re-run."
fi
chmod 600 "$APP_DIR/.env" 2>/dev/null || true

# ---- systemd ----
sudo tee /etc/systemd/system/nukkad.service >/dev/null <<UNIT
[Unit]
Description=Nukkad - magicpin Vera challenge bot
After=network.target

[Service]
User=ubuntu
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
Environment=PYTHONUTF8=1
ExecStart=$APP_DIR/.venv/bin/uvicorn bot.app:app --host 127.0.0.1 --port 8080 --workers 1 --log-level warning
Restart=always
RestartSec=2
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now nukkad
sleep 2
sudo systemctl --no-pager --lines=5 status nukkad || true

# ---- caddy (HTTPS) ----
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -y && sudo apt-get install -y caddy
fi
sudo tee /etc/caddy/Caddyfile >/dev/null <<CADDY
$HOST {
    encode gzip
    reverse_proxy 127.0.0.1:8080 {
        transport http {
            read_timeout 60s
        }
    }
}
CADDY
sudo systemctl reload caddy || sudo systemctl restart caddy

echo
echo "==> local check:"; curl -s http://127.0.0.1:8080/v1/healthz; echo
echo "==> public URL: https://$HOST   (first HTTPS request may take ~10s while the certificate is issued)"
