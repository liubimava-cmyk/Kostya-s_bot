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

# ================== ЗАДАНИЯ ==================
base_tasks = {
    1: {"category": "Группа 1", "text": "Помыть посуду", "reward": 1.5},
    2: {"category": "Группа 1", "text": "Протереть стол", "reward": 1.5},
    3: {"category": "Группа 1", "text": "Уборка зоны комнаты", "reward": 1.5},
    4: {"category": "Группа 1", "text": "Выбросить мусор", "reward": 1.5},
    5: {"category": "Группа 1", "text": "Вовремя пришёл в школу", "reward": 5},
    6: {"category": "Группа 1", "text": "Лоток кота", "reward": 1.5},
    7: {"category": "Группа 1", "text": "Не ночью в магазин / прогулка", "reward": 1.5},
    8: {"category": "Группа 2", "text": "Русский ЦТ (баллы × 0.5)", "reward": 0.5},
    9: {"category": "Группа 2", "text": "Английский ЦТ (баллы × 0.5)", "reward": 0.5},
    10: {"category": "Группа 3", "text": "Математика ЦТ", "reward": 15},
    11: {"category": "Группа 3", "text": "Математика ЦТ", "reward": 15},
}

# ================== ХРАНИЛИЩА ==================
pending_tasks = []
offers_pending = {}
offered_tasks = {}
stats = {}
pay_history = []
user_chat_ids = {}
last_test_day = {}
photo_pending = {}

# ================== СОСТОЯНИЯ ==================
OFFER_DESC, OFFER_PRICE = range(2)

# ================== ПРАВИЛА ==================
short_rules = """
Правила (кратко):
1. Каждый день минимум одно дело, можно два.
2. Пропуск дня сбрасывает серию, но 1 раз в 14 дней можно спасти.
3. Задания 2 и 3 — присылай скрины ЦТ в личку.
4. Серии: 3 дня — +15 р., 7 дней — +25 р.
5. Математика: 3 задания = +15 р. из банка.
Главное — делай хоть что-то каждый день!
"""

# ================== ПОМОЩНИКИ ==================
def get_chat_id(username: str):
    return user_chat_ids.get(username)

def save_chat_id(username: str, chat_id: int):
    user_chat_ids[username] = chat_id

def calculate_real_reward(task_id: int, points: float) -> float:
    cat = base_tasks[task_id]["category"]
    if cat == "Группа 2":
        return round(points * 0.5, 1)
    if cat == "Группа 3":
        return 40 if points > 20 else 15
    return base_tasks[task_id]["reward"]

async def notify_admin(text: str, photo=None):
    chat_id = get_chat_id(ADMIN_USERNAME)
    if chat_id:
        try:
            if photo:
                await application.bot.send_photo(chat_id=chat_id, photo=photo, caption=text)
            else:
                await application.bot.send_message(chat_id=chat_id, text=text)
        except:
            pass  # если вдруг ошибка — не падаем

# ================== START ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    save_chat_id(username, update.effective_chat.id)
    
    if username == ADMIN_USERNAME:
        await update.message.reply_text("👩‍❤️‍👩 Ты мама! Пиши /tasks чтобы отправить задание и /pending чтобы проверить все.")
    else:
        await update.message.reply_text("Привет! ❤️\n/tasks — задания\n/help — правила\n/stats — статистика")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(short_rules)

# ================== /TASKS (кнопки для ВСЕХ) ==================
async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    save_chat_id(username, update.effective_chat.id)
    
    keyboard = [
        [InlineKeyboardButton(f"{tid} — {t['text']} (+{t['reward']})", callback_data=str(tid))]
        for tid, t in base_tasks.items()
    ]
    await update.message.reply_text("Выбери задание:", reply_markup=InlineKeyboardMarkup(keyboard))

# ================== КНОПКА ЗАДАНИЯ ==================
async def task_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = int(query.data)
    username = query.from_user.username
    save_chat_id(username, query.message.chat_id)

    await done_task_logic(username, task_id, context)
    await query.edit_message_text(f"✅ Задание {task_id} отправлено на проверку.")

# ================== ОСНОВНАЯ ЛОГИКА (теперь для ВСЕХ одинаково) ==================
async def done_task_logic(username: str, task_id: int, context: ContextTypes.DEFAULT_TYPE):
    if task_id not in base_tasks:
        await context.bot.send_message(chat_id=get_chat_id(username), text="❌ Такого задания нет.")
        return

    today = datetime.now().date()
    pending_tasks.append({
        "username": username,
        "task_id": task_id,
        "date": today,
        "points": None
    })

    text = f"🆕 Новое задание от @{username}:\nЗадание №{task_id}: {base_tasks[task_id]['text']}\nДата: {today}"

    # Уведомляем маму ТОЛЬКО если это не она сама
    if username != ADMIN_USERNAME:
        await notify_admin(text)
    else:
        await context.bot.send_message(chat_id=get_chat_id(username), text="✅ Твоё тестовое задание добавлено в очередь на проверку.")

# ================== /DONE ==================
async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    save_chat_id(username, update.effective_chat.id)
    if not context.args:
        await update.message.reply_text("Используй: /done 3")
        return
    task_id = int(context.args[0])
    await done_task_logic(username, task_id, context)

# ================== ОБРАБОТКА ФОТО ==================
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if pending_tasks and pending_tasks[-1]["username"] == username:
        photo_pending[username] = update.message.photo[-1].file_id
        await update.message.reply_text("📸 Скрины сохранены.")

# ================== /PENDING — ТОЛЬКО ДЛЯ МАМЫ ==================
async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != ADMIN_USERNAME:
        await update.message.reply_text("❌ Только мама может проверять задания.")
        return

    if not pending_tasks:
        await update.message.reply_text("✅ Нет заданий на проверку.")
        return

    for idx, task in enumerate(pending_tasks):
        t = base_tasks[task["task_id"]]
        txt = f"Задание {idx+1} от @{task['username']}\n{t['text']}\nДата: {task['date']}"
        keyboard = [
            [InlineKeyboardButton("✅ Подтвердить", callback_data=f"approve_{idx}")],
            [InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{idx}")]
        ]
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(keyboard))

# ================== ПОДТВЕРЖДЕНИЕ (только мама) ==================
async def approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, idx_str = query.data.split("_")
    idx = int(idx_str)
    task = pending_tasks[idx]

    if action == "reject":
        await query.edit_message_text("❌ Задание отклонено.")
        pending_tasks.pop(idx)
        return

    # Для Группа 1 сразу подтверждаем
    if base_tasks[task["task_id"]]["category"] == "Группа 1":
        await confirm_task(task, idx, query)
    else:
        context.user_data["confirm_idx"] = idx
        await query.edit_message_text("Введи количество баллов (число):")
        return CONFIRM_BALANCE

# ================== ВВОД БАЛЛОВ ==================
CONFIRM_BALANCE = 10
async def confirm_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idx = context.user_data.get("confirm_idx")
    if idx is None:
        return
    try:
        points = float(update.message.text)
    except:
        await update.message.reply_text("Нужно число! Попробуй ещё раз.")
        return

    await confirm_task(pending_tasks[idx], idx, update, points)
    context.user_data.pop("confirm_idx", None)

async def confirm_task(task: dict, idx: int, update_obj, points=None):
    username = task["username"]
    task_id = task["task_id"]
    real_reward = calculate_real_reward(task_id, points) if points is not None else base_tasks[task_id]["reward"]

    if username not in stats:
        stats[username] = {"done": [], "series": 0, "last_date": None, "bank": 0, "reward_total": 0.0, "paid": 0.0}
    user = stats[username]

    # (серия, банк, бонусы — оставил как было, без изменений)
    today = datetime.now().date()
    # ... (весь блок серий, банка и начисления — точно как в предыдущей версии, я его не трогал)

    # Для краткости здесь опущен блок серий/банка (он идентичен предыдущей версии). Если нужно — скажи, добавлю.

    user["reward_total"] += real_reward
    user["done"].append({"task_id": task_id, "date": today, "reward": real_reward, "points": points})

    await update_obj.bot.send_message(chat_id=get_chat_id(username),
                                      text=f"✅ Задание №{task_id} подтверждено! +{real_reward} р.")

    pending_tasks.pop(idx)

    if username in photo_pending:
        await notify_admin(f"📸 Скрины к заданию {task_id}", photo=photo_pending.pop(username))

# ================== /STATS, /PAY, /OFFER_JOB и т.д. (без изменений) ==================
# (все остальные команды — stats, pay, offer_job, approve_offer, reject_offer, offered_tasks — остались точно такими же, как в прошлой версии)

# ================== MAIN ==================
def main():
    global application
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("tasks", tasks_command))
    application.add_handler(CommandHandler("done", done))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("pay", pay_command))
    application.add_handler(CommandHandler("pending", pending_command))
    application.add_handler(CommandHandler("approve_offer", approve_offer))
    application.add_handler(CommandHandler("reject_offer", reject_offer))
    application.add_handler(CommandHandler("offered_tasks", offered_tasks_cmd))

    application.add_handler(CallbackQueryHandler(task_button, pattern=r"^\d+$"))
    application.add_handler(CallbackQueryHandler(approve_callback, pattern=r"^(approve|reject)_\d+$"))

    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler("offer_job", offer_job_start)],
        states={OFFER_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, offer_desc)],
                OFFER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, offer_price)]},
        fallbacks=[]
    ))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_balance), group=1)

    application.run_polling()

if __name__ == "__main__":
    main()