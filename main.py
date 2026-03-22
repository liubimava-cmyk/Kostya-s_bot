import os
import datetime
from collections import defaultdict

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
import os
import json
from oauth2client.service_account import ServiceAccountCredentials

scope = ["https://spreadsheets.google.com/feeds",'https://www.googleapis.com/auth/drive']

# Загружаем JSON из переменной окружения
creds_json = os.environ.get("GOOGLE_SHEET_JSON_STR")
creds_dict = json.loads(creds_json)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
GOOGLE_SHEET_NAME = "Motivation_Log"

ADMIN_USERNAME = "Lbimova"

# ================= GOOGLE =================
scope = [
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/drive'
]

creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_SHEET_JSON, scope)
gc = gspread.authorize(creds)
sheet = gc.open(GOOGLE_SHEET_NAME).sheet1

def log_event(username, event_type, amount=0, balance=0, comment=""):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([now, username, event_type, amount, balance, comment])

# ================= DATA =================
users = {}
tasks = {}
task_counter = 1

offers = {"pending": [], "approved": []}
ledger = []

insurance_used = defaultdict(bool)
daily_levels = defaultdict(list)

# состояния диалогов
user_states = {}

# ================= CONSTANTS =================
STATUS_AVAILABLE = "AVAILABLE"
STATUS_SUBMITTED = "SUBMITTED"
STATUS_APPROVED = "APPROVED"
STATUS_REJECTED = "REJECTED"

# ================= HELPERS =================
def today():
    return datetime.date.today()

def get_balance(username):
    return sum(x["amount"] for x in ledger if x["username"] == username)

def approved_today(username):
    return [
        t for t in tasks.values()
        if t["executor"] == username
        and t["status"] == STATUS_APPROVED
        and t["date"] == today()
    ]

def can_do_more(username):
    return len(approved_today(username)) < 3

def add_money(username, amount, event_type, comment=""):
    ledger.append({
        "username": username,
        "amount": amount,
        "type": event_type
    })
    log_event(username, event_type, amount, get_balance(username), comment)

# ================= SERIES =================
def update_series(username):
    user = users[username]
    last = user.get("last_date")

    if last:
        diff = (today() - last).days
        if diff == 1:
            user["series"] += 1
        elif diff == 2 and not insurance_used[username]:
            insurance_used[username] = True
            last_day = today() + datetime.timedelta(days=14)
            return f"🚨 СТРАХОВОЧНЫЙ ДЕНЬ ИСПОЛЬЗОВАН!\nДо {last_day.strftime('%d.%m')} выполняй задания каждый день!"
        else:
            user["series"] = 1
    else:
        user["series"] = 1

    user["last_date"] = today()

    if user["series"] == 5:
        add_money(username, 10, "SERIES_BONUS")
    if user["series"] == 9:
        add_money(username, 25, "SERIES_BONUS")

    return None

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username

    if username not in users:
        users[username] = {
            "series": 0,
            "bank_counter": 0,
            "last_date": None
        }
        await update.message.reply_text("Введи логин выполняющего задания")
        user_states[username] = "SET_NAME"
    else:
        await update.message.reply_text("Бот готов")

# ================= TASKS =================
async def tasks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Посуда (1.5)", callback_data="task_1")],
        [InlineKeyboardButton("Мусор (1.5)", callback_data="task_2")],
        [InlineKeyboardButton("Математика", callback_data="task_3")]
    ]
    await update.message.reply_text("Выбери задание:", reply_markup=InlineKeyboardMarkup(keyboard))

async def task_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global task_counter
    query = update.callback_query
    await query.answer()

    username = query.from_user.username

    if not can_do_more(username):
        await query.edit_message_text("Лимит 3 задания достигнут")
        return

    task_map = {
        "task_1": ("Посуда", 1, 1.5),
        "task_2": ("Мусор", 1, 1.5),
        "task_3": ("Математика", 3, 40)
    }

    title, level, reward = task_map[query.data]

    task_id = str(task_counter)
    task_counter += 1

    tasks[task_id] = {
        "id": task_id,
        "title": title,
        "level": level,
        "reward": reward,
        "status": STATUS_SUBMITTED,
        "executor": username,
        "date": today()
    }

    await query.edit_message_text(f"Отправлено на проверку: {title}")

# ================= ADMIN =================
async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != ADMIN_USERNAME:
        return

    for t in tasks.values():
        if t["status"] == STATUS_SUBMITTED:
            keyboard = [
                [
                    InlineKeyboardButton("✅", callback_data=f"approve_{t['id']}"),
                    InlineKeyboardButton("❌", callback_data=f"reject_{t['id']}")
                ]
            ]
            await update.message.reply_text(
                f"{t['id']} - {t['title']}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

async def approve_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, task_id = query.data.split("_")
    task = tasks.get(task_id)

    if not task:
        return

    username = task["executor"]

    if action == "approve":
        task["status"] = STATUS_APPROVED
        add_money(username, task["reward"], "TASK_REWARD", task["title"])

        # мат банк
        if task["level"] == 3:
            users[username]["bank_counter"] += 1
            if users[username]["bank_counter"] == 3:
                users[username]["bank_counter"] = 0
                add_money(username, 15, "MATH_BANK")

        msg = update_series(username)

        await query.edit_message_text(f"✅ {task['title']}")
        if msg:
            await query.message.reply_text(msg)

    else:
        task["status"] = STATUS_REJECTED
        await query.edit_message_text(f"❌ {task['title']}")

# ================= OFFER JOB =================
async def offer_job(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    user_states[username] = "OFFER_TEXT"
    await update.message.reply_text("Опиши задание:")

# ================= ADMIN INPUT =================
async def admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != ADMIN_USERNAME:
        return

    keyboard = [
        [InlineKeyboardButton("Оценка", callback_data="grade")],
        [InlineKeyboardButton("Опоздание", callback_data="late")]
    ]
    await update.message.reply_text("Что вводим?", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data["admin_action"] = query.data
    await query.edit_message_text("Введи username:")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username

    # ADMIN FLOW
    if username == ADMIN_USERNAME and "admin_action" in context.user_data:
        target = update.message.text

        if context.user_data["admin_action"] == "grade":
            context.user_data["target"] = target
            context.user_data["step"] = "grade_value"
            await update.message.reply_text("Введи оценку:")
            return

        elif context.user_data.get("step") == "grade_value":
            grade = int(update.message.text)
            target = context.user_data["target"]

            if grade > 6:
                add_money(target, 5, "GRADE")
            elif grade >= 5:
                add_money(target, -3, "GRADE")
            else:
                add_money(target, -10, "GRADE")

            await update.message.reply_text("Оценка учтена")
            context.user_data.clear()
            return

        elif context.user_data["admin_action"] == "late":
            add_money(target, 0, "LATENESS")
            await update.message.reply_text("Опоздание зафиксировано")
            context.user_data.clear()
            return

# ================= RESET =================
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != ADMIN_USERNAME:
        return

    keyboard = [
        [InlineKeyboardButton("ДА", callback_data="reset_yes")],
        [InlineKeyboardButton("НЕТ", callback_data="reset_no")]
    ]
    await update.message.reply_text("Точно очистить всё?", reply_markup=InlineKeyboardMarkup(keyboard))

async def reset_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "reset_yes":
        global users, tasks, ledger
        users = {}
        tasks = {}
        ledger = []
        log_event("system", "CLEANED", 0, 0, "reset")
        await query.edit_message_text("Система очищена")
    else:
        await query.edit_message_text("Отмена")

# ================= RUN =================
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("tasks", tasks_cmd))
app.add_handler(CommandHandler("pending_tasks", pending))
app.add_handler(CommandHandler("offer_job", offer_job))
app.add_handler(CommandHandler("admin_input", admin_input))
app.add_handler(CommandHandler("reset", reset))

app.add_handler(CallbackQueryHandler(task_select, pattern="task_"))
app.add_handler(CallbackQueryHandler(approve_reject, pattern="approve_|reject_"))
app.add_handler(CallbackQueryHandler(admin_choice, pattern="grade|late"))
app.add_handler(CallbackQueryHandler(reset_confirm, pattern="reset_"))

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

app.run_polling()