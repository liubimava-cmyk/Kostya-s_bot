# Деплой Kostya Bot на Oracle Cloud

## Первый запуск

### 1. Подключись к серверу по SSH
```bash
ssh -i ~/Downloads/ключ.pem ubuntu@<PUBLIC_IP>
```

### 2. Скопируй setup.sh на сервер
```bash
scp -i ~/Downloads/ключ.pem setup.sh ubuntu@<PUBLIC_IP>:~/
```
Или прямо на сервере:
```bash
curl -o setup.sh https://raw.githubusercontent.com/liubimava-cmyk/Kostya-s_bot/main/oracle_deploy/setup.sh
```

### 3. Запусти установку
```bash
bash setup.sh
```
Скрипт спросит `BOT_TOKEN` и `GOOGLE_SHEET_JSON_STR` — вставь из Railway.

---

## Обновление после git push

```bash
ssh -i ~/Downloads/ключ.pem ubuntu@<PUBLIC_IP>
bash ~/kostya_bot/deploy.sh
```

---

## Полезные команды

| Что сделать | Команда |
|---|---|
| Смотреть логи в реальном времени | `sudo journalctl -u kostya-bot -f` |
| Статус бота | `sudo systemctl status kostya-bot` |
| Перезапустить | `sudo systemctl restart kostya-bot` |
| Остановить | `sudo systemctl stop kostya-bot` |
| Запустить | `sudo systemctl start kostya-bot` |

---

## Переменные окружения

Хранятся в `~/kostya_bot/.env` (chmod 600 — только ты можешь читать).

Если нужно изменить:
```bash
nano ~/kostya_bot/.env
sudo systemctl restart kostya-bot
```

---

## Примечание по Webhook

На Oracle Cloud бот работает в режиме **polling** (WEBHOOK_URL не задан).
Это нормально — фоновая Sheets-очередь всё равно даёт быстрые ответы.

Если захочешь webhook: нужен домен + SSL (nginx + certbot).
Напиши — помогу настроить.
