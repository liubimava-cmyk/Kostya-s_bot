#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# setup.sh — одноразовая установка Kostya Bot на Oracle Cloud (Ubuntu 22.04)
# Запускать: bash setup.sh
# ══════════════════════════════════════════════════════════════════════════════
set -e

REPO="https://github.com/liubimava-cmyk/Kostya-s_bot.git"
APP_DIR="$HOME/kostya_bot"
SERVICE_NAME="kostya-bot"
PYTHON="python3.11"

echo ""
echo "══════════════════════════════════════════"
echo "  Kostya Bot — Setup on Oracle Cloud"
echo "══════════════════════════════════════════"
echo ""

# ── 1. Обновляем систему ──────────────────────────────────────────────────────
echo "[1/7] Updating system packages..."
sudo apt-get update -y && sudo apt-get upgrade -y -q

# ── 2. Устанавливаем Python 3.11 ──────────────────────────────────────────────
echo "[2/7] Installing Python 3.11..."
sudo apt-get install -y python3.11 python3.11-venv python3-pip git curl

# ── 3. Клонируем репозиторий ──────────────────────────────────────────────────
echo "[3/7] Cloning repository..."
if [ -d "$APP_DIR" ]; then
    echo "  Directory exists, pulling latest..."
    cd "$APP_DIR" && git pull
else
    git clone "$REPO" "$APP_DIR"
    cd "$APP_DIR"
fi

# ── 4. Создаём виртуальное окружение и ставим зависимости ─────────────────────
echo "[4/7] Setting up Python virtual environment..."
cd "$APP_DIR"
$PYTHON -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
deactivate

# ── 5. Создаём файл переменных окружения ─────────────────────────────────────
echo "[5/7] Setting up environment variables..."
ENV_FILE="$APP_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    echo "  .env already exists, skipping."
else
    echo ""
    echo "  Введи значения переменных окружения:"
    echo ""

    read -p "  BOT_TOKEN: " BOT_TOKEN
    echo ""
    echo "  GOOGLE_SHEET_JSON_STR — вставь JSON одной строкой (из Railway):"
    read -p "  > " GOOGLE_JSON
    echo ""

    cat > "$ENV_FILE" << EOF
BOT_TOKEN=${BOT_TOKEN}
GOOGLE_SHEET_JSON_STR=${GOOGLE_JSON}
EOF
    chmod 600 "$ENV_FILE"   # только владелец может читать
    echo "  .env создан."
fi

# ── 6. Устанавливаем systemd-сервис ──────────────────────────────────────────
echo "[6/7] Installing systemd service..."
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=Kostya Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${APP_DIR}/venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl start "$SERVICE_NAME"

# ── 7. Проверяем статус ───────────────────────────────────────────────────────
echo "[7/7] Checking bot status..."
sleep 3
sudo systemctl status "$SERVICE_NAME" --no-pager -l

echo ""
echo "══════════════════════════════════════════"
echo "  Готово! Бот запущен на Oracle Cloud."
echo ""
echo "  Полезные команды:"
echo "  Логи:         sudo journalctl -u $SERVICE_NAME -f"
echo "  Статус:       sudo systemctl status $SERVICE_NAME"
echo "  Перезапуск:   sudo systemctl restart $SERVICE_NAME"
echo "  Обновление:   bash ~/kostya_bot/deploy.sh"
echo "══════════════════════════════════════════"
