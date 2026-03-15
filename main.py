import logging
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

import os

TOKEN = os.environ.get("TOKEN")
ADMIN_USERNAME = "Lbimova"

# ------------------------
# Логирование
# ------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ------------------------
# База данных
# ------------------------
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS stats (
    user TEXT,
    task_id INTEGER,
    date TEXT,
    reward REAL,
    is_test INTEGER
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS pending_tasks (
    user TEXT,
    task_id INTEGER,
    date TEXT,
    points_input REAL,
    is_test INTEGER
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS payments (
    user TEXT,
    amount REAL,
    date TEXT,
    comment TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS used_safety_day (
    user TEXT,
    week_start TEXT
)
""")

conn.commit()

# ------------------------
# Задания
# ------------------------
tasks = {
    1: {"category": 1, "text": "Помыть посуду", "reward": 1.5},
    2: {"category": 1, "text": "Протереть стол", "reward": 1.5},
    3: {"category": 1, "text": "Уборка зоны комнаты", "reward": 1.5},
    4: {"category": 1, "text": "Выбросить мусор", "reward": 1.5},
    5: {"category": 1, "text": "Вовремя пришёл в школу", "reward": 5},
    6: {"category": 1, "text": "Лоток кота", "reward": 1.5},
    7: {"category": 1, "text": "Не ночью в магазин / прогулка", "reward": 1.5},
    8: {"category": 2, "text": "Русский ЦТ (баллы × коэффициент)", "reward": 0.5},
    9: {"category": 2, "text": "Английский ЦТ (баллы × коэффициент)", "reward": 0.5},
    10: {"category": 3, "text": "Математика ЦТ до 20 баллов", "reward": 15},
    11: {"category": 3, "text": "Математика ЦТ выше 20 баллов", "reward": 40}
}

# ------------------------
# Краткие правила для Кости
# ------------------------
short_rules = """
Правила системы мотивации

1. Каждый день минимум одно дело. Можно два.
2. Пропустил день — серия сбрасывается, но 1 раз в неделю можно спасти серию, сделав 2 задания на следующий день.
3. Задания:
   Уровень 1 (простое, 1,5 р.): посуда, лоток, мусор, стол, убрать часть комнаты, магазин не ночью.
   Уровень 2 (русский/английский): решить ЦТ (коэфф. 0,5) или разбор темы по русскому (35 руб.)
   Уровень 3 (математика): ЦТ: ≤20 баллов — 15 р., >20 — 40 р.
4. Нельзя более 2 дней подряд делать только лёгкие задания или только средние.
5. Серии дают бонусы:
   • 3 дня подряд — +15 р.
   • 7 дней подряд — +25 р.
6. Математика даёт накопительный бонус: за 3 выполненных задания — +15 р., можно увеличить в будущем.
7. Хорошая оценка (>6) заменяет одно задание.
8. Плохая оценка — нужно отработать за неделю.
Главное: делай хоть что-то каждый день. Серия растёт шаг за шагом.
"""

# ------------------------
# Вспомогательные функции
# ------------------------
def get_user_series(user):
    cur.execute("SELECT DISTINCT date FROM stats WHERE user=? ORDER BY date ASC", (user,))
    dates = [datetime.fromisoformat(r[0]).date() for r in cur.fetchall()]
    series = 0
    if not dates:
        return series
    today = datetime.today().date()
    last_day = today
    for d in reversed(dates):
        if (last_day - d).days <= 1:
            series += 1
            last_day = d
        else:
            break
    return series

def used_safety_day(user):
    today = datetime.today().date()
    week_start = today - timedelta(days=today.weekday())
    cur.execute("SELECT 1 FROM used_safety_day WHERE user=? AND week_start=?", (user, week_start.isoformat()))
    return cur.fetchone() is not None

def mark_safety_day_used(user):
    today = datetime.today().date()
    week_start = today - timedelta(days=today.weekday())
    cur.execute("INSERT INTO used_safety_day(user, week_start) VALUES(?,?)", (user, week_start.isoformat()))
    conn.commit()

def calculate_reward(user, task_id, points_input=None):
    base = tasks[task_id]["reward"]
    if task_id in (8, 9) and points_input is not None:
        base = base * points_input
    return base

def get_total_rewards(user):
    cur.execute("SELECT SUM(reward) FROM stats WHERE user=?", (user,))
    total = cur.fetchone()[0]
    if total is None:
        total = 0
    cur.execute("SELECT SUM(amount) FROM payments WHERE user=?", (user,))
    paid = cur.fetchone()[0]
    if paid is None:
        paid = 0
    return total, paid, total - paid

# ------------------------
# Меню команд (кнопки)
# ------------------------
def build_menu(username):
    buttons = [[KeyboardButton("/tasks"), KeyboardButton("/help")]]
    if username.lower() == "kostya":
        buttons.append([KeyboardButton("/done"), KeyboardButton("/stats")])
    if username.lower() == ADMIN_USERNAME.lower():
        buttons.append([KeyboardButton("/approve"), KeyboardButton("/addtask"), KeyboardButton("/stats"), KeyboardButton("/pay")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

# ------------------------
# Переменные для тестового режима
# ------------------------
test_mode_user = None

# ------------------------
# Хэндлеры
# ------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    await update.message.reply_text(
        f"Привет! Я бот системы мотивации.\n\nНапиши /tasks чтобы увидеть задания.\nНапиши /help чтобы прочитать правила.",
        reply_markup=build_menu(username)
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(short_rules)

async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    text = "Привет! Вот список доступных заданий:\n\n*не просто любое задание, Костя — ПРОЧИТАЙ ПРАВИЛА по команде /help*\n\n"
    for t in tasks:
        cat = tasks[t]["category"]
        reward = tasks[t]["reward"]
        text += f"{t} — {tasks[t]['text']} (ур. {cat}, +{reward})\n"
    # Проверка пропущенного дня и страховочного дня
    last_date = cur.execute("SELECT MAX(date) FROM stats WHERE user=?", (username,)).fetchone()[0]
    if last_date:
        last_date_dt = datetime.fromisoformat(last_date).date()
        today = datetime.today().date()
        if (today - last_date_dt).days > 1:
            if not used_safety_day(username):
                text += "\nВнимание! Пропущен день. Можно использовать страховочный день 1 раз в неделю."
            else:
                text += "\nВнимание! Серия прерывается, бонусы обнуляются."
    await update.message.reply_text(text, reply_markup=build_menu(username))

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global test_mode_user
    username = update.effective_user.username
    target_user = test_mode_user if test_mode_user else username
    if not context.args:
        await update.message.reply_text("Напиши номер задания: /done 1")
        return
    try:
        task_id = int(context.args[0])
    except:
        await update.message.reply_text("Неверный номер задания.")
        return
    if task_id not in tasks:
        await update.message.reply_text("Такого задания нет.")
        return
    points_input = None
    if tasks[task_id]["category"] in (2,3):
        # Для ЦТ просим ввести баллы после выполнения
        if len(context.args) > 1:
            try:
                points_input = float(context.args[1])
            except:
                points_input = None
    cur.execute("INSERT INTO pending_tasks(user, task_id, date, points_input, is_test) VALUES(?,?,?,?,?)",
                (target_user, task_id, datetime.today().isoformat(), points_input, 1 if test_mode_user else 0))
    conn.commit()
    await update.message.reply_text(f"Задание '{tasks[task_id]['text']}' отправлено маме на проверку.")

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global test_mode_user
    username = update.effective_user.username
    if username != ADMIN_USERNAME:
        await update.message.reply_text("Команда только для администратора.")
        return
    pending = cur.execute("SELECT rowid, user, task_id, points_input, is_test FROM pending_tasks").fetchall()
    if not pending:
        await update.message.reply_text("Нет заданий на подтверждение.")
        return
    text = "Подтверждённые задания:\n\n"
    for rowid, user, task_id, points_input, is_test in pending:
        reward = calculate_reward(user, task_id, points_input)
        cur.execute("INSERT INTO stats(user, task_id, date, reward, is_test) VALUES(?,?,?,?,?)",
                    (user, task_id, datetime.today().isoformat(), reward, is_test))
        text += f"{user}: {tasks[task_id]['text']} (+{reward}){' (TEST)' if is_test else ''}\n"
    cur.execute("DELETE FROM pending_tasks")
    conn.commit()
    await update.message.reply_text(text)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    total, paid, left = get_total_rewards(username)
    text = f"Статистика для {username}:\n\nВсего начислено: {total}\nВыдано: {paid}\nОстаток: {left}\n"
    user_stats = cur.execute("SELECT task_id, date, reward, is_test FROM stats WHERE user=? ORDER BY date", (username,)).fetchall()
    for task_id, date, reward, is_test in user_stats:
        text += f"{date}: {tasks[task_id]['text']} (+{reward}){' (TEST)' if is_test else ''}\n"
    await update.message.reply_text(text, reply_markup=build_menu(username))

async def addtask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if username != ADMIN_USERNAME:
        await update.message.reply_text("Команда только для администратора.")
        return
    await update.message.reply_text("Добавление задания пока не реализовано.")

async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if username != ADMIN_USERNAME:
        await update.message.reply_text("Команда только для администратора.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /pay <user> <amount>")
        return
    user = context.args[0]
    try:
        amount = float(context.args[1])
    except:
        await update.message.reply_text("Неверная сумма.")
        return
    cur.execute("INSERT INTO payments(user, amount, date, comment) VALUES(?,?,?,?)",
                (user, amount, datetime.today().isoformat(), "Выплата"))
    conn.commit()
    await update.message.reply_text(f"Выплата {amount} р. для {user} учтена.")

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global test_mode_user
    username = update.effective_user.username
    if username != ADMIN_USERNAME:
        await update.message.reply_text("Только администратор может включать тестовый режим.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /test <username>")
        return
    test_mode_user = context.args[0]
    await update.message.reply_text(f"Тестовый режим включён для {test_mode_user}.")

async def test_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global test_mode_user
    username = update.effective_user.username
    if username != ADMIN_USERNAME:
        await update.message.reply_text("Только администратор может выключать тестовый режим.")
        return
    test_mode_user = None
    await update.message.reply_text("Тестовый режим выключен.")

# ------------------------
# Основной запуск
# ------------------------
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("tasks", tasks_command))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("addtask", addtask))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("test", test))
    app.add_handler(CommandHandler("test_off", test
