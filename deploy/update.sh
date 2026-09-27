#!/usr/bin/env bash
# Redeploy after code changes. Run on the server from the repo checkout:
#   bash deploy/update.sh
set -euo pipefail
APP_DIR="/opt/nukkad"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
sudo rsync -a --delete --exclude '.git' --exclude '.env' --exclude 'logs' --exclude '.venv' --exclude 'expanded' --exclude 'aws-key' \
  "$REPO_DIR/" "$APP_DIR/"
sudo chown -R ubuntu:ubuntu "$APP_DIR"
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
sudo systemctl restart nukkad
sleep 2
curl -s http://127.0.0.1:8080/v1/healthz; echo
