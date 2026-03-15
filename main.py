import logging
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, ConversationHandler, MessageHandler, filters
)

# --- TOKEN из переменной окружения Railway ---
TOKEN = os.environ.get("TOKEN")
ADMIN_USERNAME = "Lbimova"
KOSTYA_USERNAME = "kxstik_smerch"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# --- ЗАДАНИЯ ---
base_tasks = {
    1: {"category": "Группа 1", "text": "Помыть посуду", "reward": 1.5},
    2: {"category": "Группа 1", "text": "Протереть стол", "reward": 1.5},
    3: {"category": "Группа 1", "text": "Уборка зоны комнаты", "reward": 1.5},
    4: {"category": "Группа 1", "text": "Выбросить мусор", "reward": 1.5},
    5: {"category": "Группа 1", "text": "Вовремя пришёл в школу", "reward": 5},
    6: {"category": "Группа 1", "text": "Лоток кота", "reward": 1.5},
    7: {"category": "Группа 1", "text": "Не ночью в магазин / прогулка", "reward": 1.5},
    8: {"category": "Группа 2", "text": "Русский ЦТ (баллы × коэффициент)", "reward": 0.5},
    9: {"category": "Группа 2", "text": "Английский ЦТ (баллы × коэффициент)", "reward": 0.5},
    10: {"category": "Группа 3", "text": "Математика ЦТ до 20 баллов", "reward": 15},
    11: {"category": "Группа 3", "text": "Математика ЦТ выше 20 баллов", "reward": 40},
}

# --- ХРАНЕНИЕ ДАННЫХ ---
pending_tasks = []        # задания на проверку мамой
offers_pending = {}       # предложения Кости до одобрения
offered_tasks = {}        # утверждённые предложения
stats = {}                # статистика по username
pay_history = []          # история выплат
approved_temp = []        # временные данные для интерактивного одобрения
last_test_day = {}        # дата использования страховочного дня

# --- CONSTANTS ---
OFFER_DESC, OFFER_PRICE, APPROVE_ASK = range(3)

# --- HELP ---
short_rules = """
Правила (кратко):
1. Каждый день минимум одно дело, можно два.
2. Пропуск дня сбрасывает серию, 1 раз в 14 дней можно спасти серию.
3. Задания 1: посуда, лоток, мусор, стол, убрать часть комнаты, магазин не ночью.
   Задания 2 и 3: присылай скрины ЦТ в личку.
4. Задания 2/3: деньги по коэффициенту.
5. Задания 3: ≤20 баллов — 15 р., >20 — 40 р.
6. Серии: 3 дня — +15 р., 7 дней — +25 р.
7. Математика: 3 задания — +15 р. в банк.
Главное: делай хоть что-то каждый день!
"""

# --- START ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот системы мотивации.\n"
        "Напиши /tasks чтобы увидеть задания.\n"
        "Напиши /help чтобы прочитать правила."
    )

# --- HELP ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(short_rules)

# --- TASKS с кнопками ---
async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if not username:
        await update.message.reply_text("Нужен username Telegram для использования бота.")
        return
    keyboard = [
        [InlineKeyboardButton(f"{tid} — {t['text']} (+{t['reward']})", callback_data=str(tid))]
        for tid, t in base_tasks.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите задание:", reply_markup=reply_markup)

# --- CALLBACK для кнопок ---
async def task_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = int(query.data)
    username = query.from_user.username
    await done_task_logic(username, task_id, context, test_mode=(username==ADMIN_USERNAME))
    await query.edit_message_text(
        text=f"Задание {task_id} выбрано. Используй /done {task_id} для фиксации."
    )

# --- DONE ---
async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if not username:
        await update.message.reply_text("Нужен username Telegram для использования бота.")
        return
    if not context.args:
        await update.message.reply_text("Напиши номер задания: /done 1")
        return
    task_id = int(context.args[0])
    test_mode = username == ADMIN_USERNAME and context.user_data.get("test_mode", False)
    await done_task_logic(username, task_id, context, test_mode)

# --- LOGIC DONE ---
async def done_task_logic(username, task_id, context, test_mode=False):
    if task_id not in base_tasks:
        return await context.bot.send_message(chat_id=context._chat_id, text="Такого задания нет.")

    today = datetime.now().date()
    if username not in stats:
        stats[username] = {"done": [], "series": 0, "last_date": None, "bank": 0, "reward_total": 0}

    user_stat = stats[username]

    # --- проверка серии и страховочного дня ---
    if user_stat["last_date"]:
        diff = (today - user_stat["last_date"]).days
        if diff > 1:
            last_test = last_test_day.get(username)
            if not last_test or (today - last_test).days >= 14:
                user_stat["series"] = 0
                last_test_day[username] = today
                await context.bot.send_message(chat_id=context._chat_id,
                                               text="Пропущен день. Серия сброшена, можно использовать 1 страховочный день за 14 дней.")
            else:
                user_stat["series"] = 0

    # --- запись выполнения ---
    user_stat["done"].append({"task_id": task_id, "date": today, "reward": base_tasks[task_id]["reward"], "test": test_mode})
    user_stat["last_date"] = today
    user_stat["reward_total"] += base_tasks[task_id]["reward"]
    if base_tasks[task_id]["category"] == "Группа 3":  # математический банк
        user_stat["bank"] += 5

    # --- pending для мамы ---
    if username == KOSTYA_USERNAME or test_mode:
        pending_tasks.append({"username": username, "task_id": task_id, "test": test_mode})
        if username != ADMIN_USERNAME:
            await context.bot.send_message(chat_id=context._chat_id,
                                           text=f"Задание {task_id} отправлено маме на проверку.")

# --- MAIN ---
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("tasks", tasks_command))
    app.add_handler(CallbackQueryHandler(task_button))
    app.add_handler(CommandHandler("done", done))

    app.run_polling()

if __name__ == "__main__":
    main()