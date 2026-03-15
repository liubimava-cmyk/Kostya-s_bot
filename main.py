import logging
import os
import sqlite3
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ===== TOKEN из переменной окружения =====
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("TOKEN не найден. Добавьте его в Environment Variables на Railway")

# ===== Администратор =====
ADMIN_USERNAME = "Lbimova"

# ===== Логи =====
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ===== База данных =====
DB_FILE = "bot_data.db"

# ===== Тестовый режим =====
# хранит временно, какой пользователь под кем тестирует
test_mode = {}

# ---- Инициализация базы ----
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # задания
    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            reward INTEGER NOT NULL
        )
    """)
    # ожидающие подтверждения
    c.execute("""
        CREATE TABLE IF NOT EXISTS pending_tasks (
            user TEXT NOT NULL,
            task_id INTEGER NOT NULL,
            FOREIGN KEY(task_id) REFERENCES tasks(id)
        )
    """)
    # статистика с флагом теста
    c.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            user TEXT NOT NULL,
            task_id INTEGER NOT NULL,
            is_test INTEGER DEFAULT 0,
            FOREIGN KEY(task_id) REFERENCES tasks(id)
        )
    """)
    conn.commit()
    conn.close()

# ---- Работа с базой ----
def get_tasks():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, text, reward FROM tasks")
    rows = c.fetchall()
    conn.close()
    return rows

def add_task_to_db(text, reward):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO tasks (text, reward) VALUES (?, ?)", (text, reward))
    conn.commit()
    conn.close()

def add_pending(user, task_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO pending_tasks (user, task_id) VALUES (?, ?)", (user, task_id))
    conn.commit()
    conn.close()

def get_pending():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user, task_id FROM pending_tasks")
    rows = c.fetchall()
    conn.close()
    return rows

def clear_pending():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM pending_tasks")
    conn.commit()
    conn.close()

def add_stat(user, task_id, is_test=0):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO stats (user, task_id, is_test) VALUES (?, ?, ?)", (user, task_id, is_test))
    conn.commit()
    conn.close()

def get_stats():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT user, SUM(t.reward), MAX(s.is_test)
        FROM stats s JOIN tasks t ON s.task_id = t.id
        GROUP BY user
    """)
    rows = c.fetchall()
    conn.close()
    return rows

# ---- Команды бота ----
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот системы мотивации.\nНапиши /tasks чтобы увидеть задания.\n/help — правила."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
Правила системы мотивации
1. Костя выполняет задания из списка.
2. После выполнения — команда /done
3. Задание отправляется маме.
4. Мама подтверждает через /approve
5. После подтверждения начисляется бонус

Команды:
/tasks — список заданий
/done — отметить выполненное
/help — правила

Администратор:
/approve — подтвердить задания
/addtask — добавить задание
/stats — статистика
/test <username> — включить тест для пользователя
/test_off — выключить тест
"""
    await update.message.reply_text(text)

async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "Привет! Вот список доступных заданий:\n\n*не просто любое задание, Костя — ПРОЧИТАЙ правила через /help*\n\n"
    tasks = get_tasks()
    if not tasks:
        text += "Список заданий пуст. Администратор может добавить через /addtask"
    else:
        for t in tasks:
            text += f"{t[0]} — {t[1]} (+{t[2]})\n"
    await update.message.reply_text(text)

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Напиши номер задания: /done 1")
        return
    try:
        task_id = int(context.args[0])
    except:
        await update.message.reply_text("Нужно указать номер задания.")
        return
    tasks_list = [t[0] for t in get_tasks()]
    if task_id not in tasks_list:
        await update.message.reply_text("Такого задания нет.")
        return
    user = update.effective_user.username
    if user in test_mode:
        acting_user = test_mode[user]
        is_test = 1
    else:
        acting_user = user
        is_test = 0
    add_pending(acting_user, task_id)
    await update.message.reply_text(f"Задание '{task_id}' отправлено на проверку от {acting_user} (test={is_test})")

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if username != ADMIN_USERNAME:
        await update.message.reply_text("Команда только для администратора.")
        return
    pending = get_pending()
    if not pending:
        await update.message.reply_text("Нет заданий на подтверждение.")
        return
    text = "Подтверждённые задания:\n\n"
    for user, task_id in pending:
        task = [t for t in get_tasks() if t[0] == task_id][0]
        text += f"{user}: {task[1]} (+{task[2]})\n"
        is_test_flag = 1 if user == test_mode.get(username) else 0
        add_stat(user, task_id, is_test_flag)
    clear_pending()
    await update.message.reply_text(text)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_stats()
    if not rows:
        await update.message.reply_text("Статистика пока пуста.")
        return
    text = "Статистика бонусов:\n\n"
    for user, total, is_test in rows:
        label = " (TEST)" if is_test else ""
        text += f"{user}: {total} баллов{label}\n"
    await update.message.reply_text(text)

async def addtask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if username != ADMIN_USERNAME:
        await update.message.reply_text("Команда только для администратора.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /addtask текст_задания награда")
        return
    try:
        reward = int(context.args[-1])
        text_task = " ".join(context.args[:-1])
    except:
        await update.message.reply_text("Неверный формат. Пример: /addtask Убрать комнату 15")
        return
    add_task_to_db(text_task, reward)
    await update.message.reply_text(f"Задание '{text_task}' (+{reward}) добавлено.")

# ---- Тестовый режим ----
async def test_mode_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if username != ADMIN_USERNAME:
        await update.message.reply_text("Команда только для администратора.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /test <username>")
        return
    target_user = context.args[0]
    test_mode[username] = target_user
    await update.message.reply_text(f"Тестовый режим включен. Действуете от имени {target_user}")

async def test_mode_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if username in test_mode:
        test_mode.pop(username)
        await update.message.reply_text("Тестовый режим выключен.")
    else:
        await update.message.reply_text("Тестовый режим уже выключен.")

# ---- Главная функция ----
def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("tasks", tasks_command))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("addtask", addtask))
    app.add_handler(CommandHandler("test", test_mode_on))
    app.add_handler(CommandHandler("test_off", test_mode_off))

    # Bot Menu
    commands = [
        BotCommand("tasks", "Список заданий"),
        BotCommand("help", "Правила"),
        BotCommand("done", "Отметить выполненное"),
        BotCommand("approve", "Подтвердить задания"),
        BotCommand("addtask", "Добавить задание"),
        BotCommand("stats", "Статистика"),
        BotCommand("test", "Тестовый режим"),
        BotCommand("test_off", "Выключить тест"),
    ]
    app.bot.set_my_commands(commands)

    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
