import logging
import os
from datetime import datetime, timedelta
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
    10: {"category": "Группа 3", "text": "Математика ЦТ (до 20 = 15 р., >20 = 40 р.)", "reward": 15},
    11: {"category": "Группа 3", "text": "Математика ЦТ (до 20 = 15 р., >20 = 40 р.)", "reward": 15},
}

# ================== ХРАНИЛИЩА ==================
pending_tasks = []          # список заданий на проверку
offers_pending = {}         # {kostya_chat_id: {"desc": , "price": }}
offered_tasks = {}          # утверждённые предложения
stats = {}                  # статистика по username
pay_history = []            # история выплат
user_chat_ids = {}          # username → chat_id
last_test_day = {}          # страховочный день
photo_pending = {}          # для привязки скрина к заданию

# ================== СОСТОЯНИЯ ==================
OFFER_DESC, OFFER_PRICE = range(2)
CONFIRM_BALANCE = 10        # состояние для ввода баллов при подтверждении

# ================== ПРАВИЛА ==================
short_rules = """
Правила (кратко):
1. Каждый день минимум одно дело, можно два.
2. Пропуск дня сбрасывает серию, но 1 раз в 14 дней можно спасти (страховочный).
3. Задания 2 и 3 — присылай скрины ЦТ в личку боту.
4. Серии: 3 дня подряд — +15 р., 7 дней подряд — +25 р.
5. Математика: за каждое задание +5 р. в банк, после 3 заданий +15 р.
6. Нельзя 3 дня подряд делать только лёгкие или только средние задания.
Главное — делай хоть что-то каждый день!
"""

# ================== ПОМОЩНИКИ ==================
def get_chat_id(username: str) -> int | None:
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
        if photo:
            await application.bot.send_photo(chat_id=chat_id, photo=photo, caption=text)
        else:
            await application.bot.send_message(chat_id=chat_id, text=text)

# ================== START & HELP ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    save_chat_id(username, update.effective_chat.id)
    await update.message.reply_text(
        "Привет! Я твой бот мотивации ❤️\n"
        "/tasks — список заданий\n"
        "/help — правила\n"
        "/stats — твоя статистика"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(short_rules)

# ================== /TASKS ==================
async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    save_chat_id(username, update.effective_chat.id)
    keyboard = [
        [InlineKeyboardButton(f"{tid} — {t['text']} (+{t['reward'] if t['category']=='Группа 1' else 'по баллам'})",
                              callback_data=str(tid))]
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

    await done_task_logic(username, task_id, context, test_mode=(username == ADMIN_USERNAME))
    await query.edit_message_text(f"✅ Задание {task_id} отправлено на проверку маме.")

# ================== ОСНОВНАЯ ЛОГИКА ЗАДАНИЯ ==================
async def done_task_logic(username: str, task_id: int, context: ContextTypes.DEFAULT_TYPE, test_mode=False):
    if task_id not in base_tasks:
        await context.bot.send_message(chat_id=get_chat_id(username), text="❌ Такого задания нет.")
        return

    today = datetime.now().date()
    if username not in stats:
        stats[username] = {"done": [], "series": 0, "last_date": None, "bank": 0, "reward_total": 0.0, "paid": 0.0}

    # Добавляем в pending (реальная статистика обновится только после подтверждения мамы)
    pending_tasks.append({
        "username": username,
        "task_id": task_id,
        "date": today,
        "test": test_mode,
        "points": None
    })

    text = f"🆕 Новое задание от {username}:\n" \
           f"Задание №{task_id}: {base_tasks[task_id]['text']}"

    if username != ADMIN_USERNAME:
        await notify_admin(text)

# ================== /DONE (ручной ввод) ==================
async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    save_chat_id(username, update.effective_chat.id)
    if not context.args:
        await update.message.reply_text("Используй: /done 3")
        return
    task_id = int(context.args[0])
    await done_task_logic(username, task_id, context, test_mode=(username == ADMIN_USERNAME))

# ================== ОБРАБОТКА ФОТО (скрины ЦТ) ==================
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if not pending_tasks or pending_tasks[-1]["username"] != username:
        return
    photo_pending[username] = update.message.photo[-1].file_id
    await update.message.reply_text("📸 Скрины сохранены и будут отправлены маме вместе с заданием.")

# ================== /PENDING (только мама) ==================
async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != ADMIN_USERNAME:
        await update.message.reply_text("❌ Только мама может проверять задания.")
        return

    if not pending_tasks:
        await update.message.reply_text("✅ Нет заданий на проверку.")
        return

    for idx, task in enumerate(pending_tasks):
        t = base_tasks[task["task_id"]]
        txt = f"Задание {idx+1}:\n{t['text']} от {task['username']}\nДата: {task['date']}"
        keyboard = [
            [InlineKeyboardButton("✅ Подтвердить", callback_data=f"approve_{idx}")],
            [InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{idx}")]
        ]
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(keyboard))

# ================== CALLBACK ПОДТВЕРЖДЕНИЯ ==================
async def approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, idx = query.data.split("_")
    idx = int(idx)
    task = pending_tasks[idx]

    if action == "reject":
        await query.edit_message_text(f"❌ Задание отклонено.")
        pending_tasks.pop(idx)
        return

    # Для Группа 1 — сразу подтверждаем
    if base_tasks[task["task_id"]]["category"] == "Группа 1":
        await confirm_task(task, idx, query, points=None)
    else:
        # Для 2 и 3 — просим баллы
        context.user_data["confirm_idx"] = idx
        await query.edit_message_text("Введите количество баллов (число):")
        return CONFIRM_BALANCE

async def confirm_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idx = context.user_data.get("confirm_idx")
    if idx is None:
        return
    try:
        points = float(update.message.text)
    except:
        await update.message.reply_text("Нужно число! Попробуй ещё раз.")
        return

    task = pending_tasks[idx]
    await confirm_task(task, idx, update, points)
    context.user_data.pop("confirm_idx", None)

async def confirm_task(task: dict, idx: int, update_obj, points=None):
    username = task["username"]
    task_id = task["task_id"]
    cat = base_tasks[task_id]["category"]
    real_reward = calculate_real_reward(task_id, points) if points is not None else base_tasks[task_id]["reward"]

    if username not in stats:
        stats[username] = {"done": [], "series": 0, "last_date": None, "bank": 0, "reward_total": 0.0, "paid": 0.0}
    user = stats[username]

    today = datetime.now().date()

    # === СЕРИЯ И СТРАХОВОЧНЫЙ ДЕНЬ ===
    if user["last_date"]:
        diff = (today - user["last_date"]).days
        if diff > 1:
            if username in last_test_day and (today - last_test_day[username]).days < 14:
                await notify_admin(f"Использован страховочный день для {username}")
            else:
                user["series"] = 0
                await notify_admin(f"Серия сброшена у {username}")
        else:
            user["series"] += 1
    else:
        user["series"] = 1

    user["last_date"] = today
    last_test_day[username] = today if task.get("test") else last_test_day.get(username)

    # Бонусы за серию
    bonus = 0
    if user["series"] == 3:
        bonus += 15
    if user["series"] == 7:
        bonus += 25

    # Математический банк
    if cat == "Группа 3":
        user["bank"] += 5
        if user["bank"] >= 15:
            bonus += 15
            user["bank"] -= 15
            await notify_admin(f"🎉 Математический банк выплачен +15 р. у {username}")

    total_today = real_reward + bonus

    user["reward_total"] += total_today
    user["done"].append({"task_id": task_id, "date": today, "reward": total_today, "points": points})

    # Уведомления
    await update_obj.bot.send_message(chat_id=get_chat_id(username),
                                      text=f"✅ Задание №{task_id} подтверждено!\n"
                                           f"Начислено: {total_today} р. (серия {user['series']})")

    pending_tasks.pop(idx)

    # Если было фото — отправляем маме
    if username in photo_pending:
        await notify_admin(f"📸 Скрины к заданию {task_id}", photo=photo_pending.pop(username))

# ================== /STATS ==================
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    save_chat_id(username, update.effective_chat.id)

    if username == ADMIN_USERNAME:
        text = "📊 Статистика всех:\n\n"
        for u, s in stats.items():
            text += f"@{u}: серия {s['series']} | всего {s['reward_total']:.1f} р. | банк {s['bank']}\n"
    else:
        if username not in stats:
            text = "Пока нет выполненных заданий."
        else:
            s = stats[username]
            text = f"Твоя статистика:\nСерия: {s['series']} дней\nВсего заработано: {s['reward_total']:.1f} р.\nМат. банк: {s['bank']} р."

    await update.message.reply_text(text)

# ================== /PAY ==================
async def pay_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != ADMIN_USERNAME:
        await update.message.reply_text("❌ Только мама может выдавать деньги.")
        return
    if not context.args:
        await update.message.reply_text("Используй: /pay 150")
        return
    amount = float(context.args[0])
    # Выдаём Косте (или первому пользователю кроме мамы)
    for u in stats:
        if u != ADMIN_USERNAME:
            stats[u]["paid"] += amount
            pay_history.append({"user": u, "amount": amount, "date": datetime.now().date()})
            await update.message.reply_text(f"💸 Выплачено {amount} р. @{u}")
            await context.bot.send_message(chat_id=get_chat_id(u), text=f"Мама выдала {amount} р. 💰")
            return

# ================== /OFFER_JOB ==================
async def offer_job_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if username != KOSTYA_USERNAME:
        await update.message.reply_text("Только Костя может предлагать работу.")
        return
    await update.message.reply_text("Опиши задачу:")
    return OFFER_DESC

async def offer_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["offer_desc"] = update.message.text
    await update.message.reply_text("Сколько хочешь за это?")
    return OFFER_PRICE

async def offer_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text)
    except:
        await update.message.reply_text("Нужно число!")
        return OFFER_PRICE

    desc = context.user_data["offer_desc"]
    offers_pending[update.effective_chat.id] = {"desc": desc, "price": price}

    await notify_admin(f"💼 Новое предложение от Кости:\n{desc}\nЦена: {price} р.\n\n"
                       f"Ответь /approve_offer или /reject_offer")
    await update.message.reply_text("Предложение отправлено маме ✅")
    return ConversationHandler.END

# ================== ОДОБРЕНИЕ ПРЕДЛОЖЕНИЙ ==================
async def approve_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != ADMIN_USERNAME:
        return
    if not offers_pending:
        await update.message.reply_text("Нет предложений.")
        return
    chat_id = list(offers_pending.keys())[0]
    offer = offers_pending[chat_id]
    offered_tasks[chat_id] = offer
    await context.bot.send_message(chat_id=chat_id, text=f"✅ Мама одобрила: {offer['desc']} за {offer['price']} р.")
    await update.message.reply_text("Предложение одобрено!")
    offers_pending.clear()

async def reject_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != ADMIN_USERNAME:
        return
    if offers_pending:
        chat_id = list(offers_pending.keys())[0]
        await context.bot.send_message(chat_id=chat_id, text="❌ Мама отклонила предложение.")
        offers_pending.clear()
        await update.message.reply_text("Предложение отклонено.")

# ================== /OFFERED_TASKS ==================
async def offered_tasks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in offered_tasks:
        await update.message.reply_text("Нет утверждённых предложений.")
        return
    o = offered_tasks[update.effective_chat.id]
    await update.message.reply_text(f"Твоя утверждённая работа:\n{o['desc']}\nЦена: {o['price']} р.")

# ================== MAIN ==================
def main():
    global application
    application = ApplicationBuilder().token(TOKEN).build()

    # Основные хендлеры
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

    # Кнопки и колбэки
    application.add_handler(CallbackQueryHandler(task_button, pattern=r"^\d+$"))
    application.add_handler(CallbackQueryHandler(approve_callback, pattern=r"^(approve|reject)_\d+$"))

    # Фото
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # Предложения работы
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler("offer_job", offer_job_start)],
        states={
            OFFER_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, offer_desc)],
            OFFER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, offer_price)]
        },
        fallbacks=[]
    ))

    # Ввод баллов при подтверждении
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_balance), group=1)

    application.run_polling()

if __name__ == "__main__":
    main()