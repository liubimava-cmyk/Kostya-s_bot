#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# deploy.sh — обновление бота с GitHub + перезапуск
# Запускать после каждого git push: bash ~/kostya_bot/deploy.sh
# ══════════════════════════════════════════════════════════════════════════════
set -e

APP_DIR="$HOME/kostya_bot"
SERVICE_NAME="kostya-bot"

echo "[Deploy] Pulling latest code from GitHub..."
cd "$APP_DIR"

BEFORE=$(git rev-parse HEAD)
git pull origin main
AFTER=$(git rev-parse HEAD)

if [ "$BEFORE" = "$AFTER" ]; then
    echo "[Deploy] No changes. Bot is already up to date."
    exit 0
fi

echo "[Deploy] Changes detected. Updating dependencies..."
source venv/bin/activate
pip install -r requirements.txt -q
deactivate

echo "[Deploy] Restarting bot service..."
sudo systemctl restart "$SERVICE_NAME"
sleep 2

STATUS=$(sudo systemctl is-active "$SERVICE_NAME")
if [ "$STATUS" = "active" ]; then
    echo "[Deploy] ✓ Bot restarted successfully."
    echo "[Deploy] Commit: $AFTER"
else
    echo "[Deploy] ✗ Bot failed to start. Check logs:"
    echo "  sudo journalctl -u $SERVICE_NAME -n 50"
    exit 1
fi
