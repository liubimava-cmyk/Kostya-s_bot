import logging
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, ConversationHandler, MessageHandler, filters
)

# ================== НАСТРОЙКИ ==================
TOKEN = os.environ.get("TOKEN")
ADMIN_USERNAME = "Lbimova"
KOSTYA_USERNAME = "kxstik_smerch"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# ================== ТЕСТОВЫЙ РЕЖИМ ==================
test_mode = False

# ================== ЗАДАНИЯ ==================
base_tasks = {
    1: {"category": "Группа 1", "text": "Помыть посуду", "reward": 1.5},
    2: {"category": "Группа 1", "text": "Протереть стол", "reward": 1.5},
    3: {"category": "Группа 1", "text": "Уборка зоны комнаты", "reward": 1.5},
    4: {"category": "Группа 1", "text": "Выбросить мусор", "reward": 1.5},
    5: {"category": "Группа 1", "text": "Вовремя пришёл в школу", "reward": 5},
    6: {"category": "Группа 1", "text": "Лоток кота", "reward": 1.5},
    7: {"category": "Группа 1", "text": "Не ночью в магазин / прогулка", "reward": 1.5},
    8: {"category": "Группа 2", "text": "Русский ЦТ", "reward": 0.5},
    9: {"category": "Группа 2", "text": "Английский ЦТ", "reward": 0.5},
    10: {"category": "Группа 3", "text": "Математика ЦТ", "reward": 15},
    11: {"category": "Группа 3", "text": "Математика ЦТ", "reward": 15},
}

# ================== ХРАНИЛИЩА ==================
pending_tasks = []
stats = {}
user_chat_ids = {}
photo_pending = {}
last_test_day = {}

# ================== СОСТОЯНИЯ ==================
OFFER_DESC, OFFER_PRICE = range(2)
CONFIRM_BALANCE = 10

# ================== ПРАВИЛА ==================
short_rules = """
Правила (кратко):
1. Каждый день минимум одно дело, можно два.
2. Пропуск дня сбрасывает серию, но 1 раз в 14 дней можно спасти.
3. Задания 2 и 3 — присылай скрины.
4. Серии: 3 дня — +15 р., 7 дней — +25 р.
5. Математика: 3 задания = +15 р. из банка.
"""

# ================== ПОМОЩНИКИ ==================
def get_chat_id(username: str):
    return user_chat_ids.get(username)

def save_chat_id(username: str, chat_id: int):
    user_chat_ids[username] = chat_id

def calculate_real_reward(task_id: int, points=None):
    cat = base_tasks[task_id]["category"]
    if cat == "Группа 2" and points: return round(points * 0.5, 1)
    if cat == "Группа 3" and points: return 40 if points > 20 else 15
    return base_tasks[task_id]["reward"]

async def notify_mom(text: str, photo=None):
    chat_id = get_chat_id(ADMIN_USERNAME)
    if chat_id:
        if photo:
            await application.bot.send_photo(chat_id=chat_id, photo=photo, caption=text)
        else:
            await application.bot.send_message(chat_id=chat_id, text=text)

# ================== START & HELP ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    save_chat_id(username, update.effective_chat.id)
    if username == ADMIN_USERNAME:
        await update.message.reply_text("👩‍❤️‍👩 Ты мама!\n/test — включить тестовый режим\n/tasks — задания\n/pending — проверка")
    else:
        await update.message.reply_text("Привет! /tasks — задания")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(short_rules)

# ================== ТЕСТОВЫЙ РЕЖИМ ==================
async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global test_mode
    if update.effective_user.username != ADMIN_USERNAME:
        await update.message.reply_text("Только мама.")
        return
    test_mode = not test_mode
    status = "✅ ВКЛЮЧЁН (задания идут от Кости)" if test_mode else "❌ ВЫКЛЮЧЕН"
    await update.message.reply_text(f"Тестовый режим: {status}\nТеперь отправляй задания — всё будет приходить тебе сразу!")

# ================== /TASKS — КНОПКИ (короткие, как в твоём старом) ==================
async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(f"{tid}. {t['text']}", callback_data=str(tid))]
        for tid, t in base_tasks.items()
    ]
    await update.message.reply_text("Выбери задание:", reply_markup=InlineKeyboardMarkup(keyboard))

async def task_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = int(query.data)
    await done_task_logic(task_id, context)
    await query.edit_message_text(f"✅ Задание {task_id} отправлено.")

# ================== ЛОГИКА ЗАДАНИЯ (с тестовым режимом) ==================
async def done_task_logic(task_id: int, context: ContextTypes.DEFAULT_TYPE):
    if task_id not in base_tasks:
        return
    username = KOSTYA_USERNAME if test_mode else context.effective_user.username
    today = datetime.now().date()

    pending_tasks.append({"username": username, "task_id": task_id, "date": today, "points": None})

    text = f"🆕 Новое задание от @{username}:\nЗадание №{task_id}: {base_tasks[task_id]['text']}\nДата: {today}"
    await notify_mom(text)   # ← сразу приходит тебе!

    await context.bot.send_message(chat_id=context.effective_chat.id,
                                   text=f"✅ Отправлено (тест: {test_mode})")

# ================== /DONE ==================
async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Используй: /done 3")
        return
    task_id = int(context.args[0])
    await done_task_logic(task_id, context)

# ================== ФОТО ==================
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if pending_tasks:
        photo_pending[pending_tasks[-1]["username"]] = update.message.photo[-1].file_id
        await update.message.reply_text("📸 Скрины сохранены.")

# ================== /PENDING ==================
async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != ADMIN_USERNAME:
        await update.message.reply_text("❌ Только мама.")
        return
    if not pending_tasks:
        await update.message.reply_text("✅ Всё проверено.")
        return
    for idx, task in enumerate(pending_tasks):
        txt = f"Задание {idx+1} от @{task['username']}\n{base_tasks[task['task_id']]['text']}"
        keyboard = [
            [InlineKeyboardButton("✅ Подтвердить", callback_data=f"approve_{idx}")],
            [InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{idx}")]
        ]
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(keyboard))

# ================== ПОДТВЕРЖДЕНИЕ + СЕРИИ + БАНК ==================
async def approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, idx = query.data.split("_")
    idx = int(idx)
    task = pending_tasks[idx]

    if action == "reject":
        await query.edit_message_text("❌ Отклонено")
        pending_tasks.pop(idx)
        return

    if base_tasks[task["task_id"]]["category"] == "Группа 1":
        await confirm_task(task, idx, query)
    else:
        context.user_data["confirm_idx"] = idx
        await query.edit_message_text("Введи баллы:")
        return CONFIRM_BALANCE

async def confirm_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idx = context.user_data.get("confirm_idx")
    if idx is None: return
    try:
        points = float(update.message.text)
    except:
        await update.message.reply_text("Нужно число!")
        return
    await confirm_task(pending_tasks[idx], idx, update, points)
    context.user_data.pop("confirm_idx", None)

async def confirm_task(task, idx, update_obj, points=None):
    username = task["username"]
    task_id = task["task_id"]
    real_reward = calculate_real_reward(task_id, points)

    if username not in stats:
        stats[username] = {"done": [], "series": 0, "last_date": None, "bank": 0, "reward_total": 0.0}
    user = stats[username]
    today = datetime.now().date()

    # Серия + страховочный день
    if user["last_date"]:
        diff = (today - user["last_date"]).days
        if diff > 1:
            user["series"] = 0
        else:
            user["series"] += 1
    else:
        user["series"] = 1
    user["last_date"] = today

    bonus = 0
    if user["series"] == 3: bonus += 15
    if user["series"] == 7: bonus += 25
    if base_tasks[task_id]["category"] == "Группа 3":
        user["bank"] += 5
        if user["bank"] >= 15:
            bonus += 15
            user["bank"] -= 15

    total = real_reward + bonus
    user["reward_total"] += total

    await update_obj.bot.send_message(chat_id=get_chat_id(ADMIN_USERNAME),
                                      text=f"✅ Задание {task_id} подтверждено! +{total} р. (серия {user['series']})")

    pending_tasks.pop(idx)

# ================== /STATS ==================
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username == ADMIN_USERNAME:
        text = "📊 Статистика:\n"
        for u, s in stats.items():
            text += f"@{u}: серия {s['series']} | всего {s['reward_total']:.1f} р.\n"
    else:
        s = stats.get(update.effective_user.username, {})
        text = f"Серия: {s.get('series', 0)} | всего {s.get('reward_total', 0):.1f} р."
    await update.message.reply_text(text)

# ================== MAIN ==================
def main():
    global application
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(CommandHandler("tasks", tasks_command))
    application.add_handler(CommandHandler("done", done))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("pending", pending_command))

    application.add_handler(CallbackQueryHandler(task_button, pattern=r"^\d+$"))
    application.add_handler(CallbackQueryHandler(approve_callback, pattern=r"^(approve|reject)_\d+$"))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_balance), group=1)

    application.run_polling()

if __name__ == "__main__":
    main()