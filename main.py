import os
import datetime
from collections import defaultdict
import json
import time

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
ADMIN_USERNAME = "Lbimova"

# ================= GOOGLE =================
GOOGLE_SHEET_NAME = "Motivation_Log"

scope = [
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/drive'
]

creds_json = os.environ.get("GOOGLE_SHEET_JSON_STR")
if not creds_json:
    raise ValueError("Переменная окружения GOOGLE_SHEET_JSON_STR не задана")

creds_dict = json.loads(creds_json)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
gc = gspread.authorize(creds)

sheet = gc.open(GOOGLE_SHEET_NAME).sheet1

# ================= SAFE APPEND =================
def safe_append(ws, row):
    for _ in range(3):
        try:
            ws.append_row(row)
            return
        except:
            time.sleep(1)

# ================= INIT SHEETS =================
def init_sheets():
    global tasks_ws, users_ws, ledger_ws

    try:
        tasks_ws = gc.open(GOOGLE_SHEET_NAME).worksheet("tasks")
    except:
        tasks_ws = gc.open(GOOGLE_SHEET_NAME).add_worksheet(title="tasks", rows="1000", cols="10")
        tasks_ws.append_row(["id","title","description","source","reward_type","reward_value","status","executor","date"])

    try:
        users_ws = gc.open(GOOGLE_SHEET_NAME).worksheet("users")
    except:
        users_ws = gc.open(GOOGLE_SHEET_NAME).add_worksheet(title="users", rows="1000", cols="10")
        users_ws.append_row(["username","series","bank_counter","last_date"])

    try:
        ledger_ws = gc.open(GOOGLE_SHEET_NAME).worksheet("ledger")
    except:
        ledger_ws = gc.open(GOOGLE_SHEET_NAME).add_worksheet(title="ledger", rows="1000", cols="10")
        ledger_ws.append_row(["timestamp","username","amount","type","comment"])

init_sheets()

# ================= DATA LOAD =================
def load_data():
    global tasks, users, ledger, task_counter

    tasks = {}
    users = {}
    ledger = []

    rows = tasks_ws.get_all_records()
    for r in rows:
        tasks[r["id"]] = r

    rows = users_ws.get_all_records()
    for r in rows:
        users[r["username"]] = {
            "series": int(r["series"]),
            "bank_counter": int(r["bank_counter"]),
            "last_date": datetime.date.fromisoformat(r["last_date"]) if r["last_date"] else None
        }

    rows = ledger_ws.get_all_records()
    for r in rows:
        ledger.append(r)

    if tasks:
        task_counter = max(int(k) for k in tasks.keys()) + 1
    else:
        task_counter = 1

load_data()

# ================= DATA =================
users = users
tasks = tasks
task_counter = task_counter
ledger = ledger

insurance_used = defaultdict(bool)
daily_levels = defaultdict(list)

user_states = {}

# ================= CONSTANTS =================
STATUS_AVAILABLE = "AVAILABLE"
STATUS_OFFERED = "OFFERED"
STATUS_SUBMITTED = "SUBMITTED"
STATUS_APPROVED = "APPROVED"
STATUS_REJECTED = "REJECTED"

SOURCE_SYSTEM = "SYSTEM"
SOURCE_USER = "USER"

# ================= CRUD =================
def save_task(task):
    safe_append(tasks_ws, [
        task["id"],
        task.get("title",""),
        task.get("description",""),
        task.get("source",""),
        task.get("reward_type",""),
        task.get("reward_value",0),
        task.get("status",""),
        task.get("executor",""),
        str(task.get("date",""))
    ])

def update_task(task_id, field, value):
    cell = tasks_ws.find(task_id)
    col_map = {
        "status": 7,
        "executor": 8
    }
    col = col_map[field]
    tasks_ws.update_cell(cell.row, col, value)

def save_user(username):
    u = users[username]

    safe_append(users_ws, [
        username,
        u["series"],
        u["bank_counter"],
        str(u["last_date"] or "")
    ])

def update_user(username):
    cell = users_ws.find(username)
    u = users[username]

    users_ws.update(f"A{cell.row}:D{cell.row}", [[
        username,
        u["series"],
        u["bank_counter"],
        str(u["last_date"] or "")
    ]])

def add_money(username, amount, event_type, comment=""):
    ledger.append({
        "username": username,
        "amount": amount,
        "type": event_type
    })

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    safe_append(ledger_ws, [
        now,
        username,
        amount,
        event_type,
        comment
    ])

# ================= HELPERS =================
def today():
    return datetime.date.today()

def get_balance(username):
    return sum(float(x["amount"]) for x in ledger if x["username"] == username)

def approved_today(username):
    return [
        t for t in tasks.values()
        if t["executor"] == username
        and t["status"] == STATUS_APPROVED
        and t["date"] == today()
    ]

def can_do_more(username):
    return len(approved_today(username)) < 3

# ================= SERIES =================
def update_series(username):
    if username not in users:
        return None

    user = users[username]
    last = user.get("last_date")

    if last:
        diff = (today() - last).days
        if diff == 1:
            user["series"] += 1
        elif diff == 2 and not insurance_used[username]:
            insurance_used[username] = True
            last_day = today() + datetime.timedelta(days=14)
            user["series"] = 1
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

    if not username:
        await update.message.reply_text("Ваш username не определён")
        return

    if username not in users:
        users[username] = {
            "series": 0,
            "bank_counter": 0,
            "last_date": None
        }
        save_user(username)

        await update.message.reply_text("Введи логин выполняющего задания")
        user_states[username] = "SET_NAME"
    else:
        await update.message.reply_text("Бот готов")

# ================= TASKS =================
async def tasks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []

    keyboard.extend([
        [InlineKeyboardButton("Посуда (1.5)", callback_data="task_sys_1")],
        [InlineKeyboardButton("Мусор (1.5)", callback_data="task_sys_2")],
        [InlineKeyboardButton("Математика", callback_data="task_sys_3")]
    ])

    for t in tasks.values():
        if t["status"] == STATUS_AVAILABLE:
            keyboard.append([
                InlineKeyboardButton(
                    f"{t['title']} ({t['reward_value']})",
                    callback_data=f"task_user_{t['id']}"
                )
            ])

    await update.message.reply_text("Выбери задание:", reply_markup=InlineKeyboardMarkup(keyboard))

async def task_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global task_counter

    query = update.callback_query
    await query.answer()

    username = query.from_user.username
    if not username:
        await query.edit_message_text("Ошибка: username не определён")
        return

    if not can_do_more(username):
        await query.edit_message_text("Лимит 3 задания достигнут")
        return

    if query.data.startswith("task_sys_"):
        task_map = {
            "task_sys_1": ("Посуда", 1, 1.5),
            "task_sys_2": ("Мусор", 1, 1.5),
            "task_sys_3": ("Математика", 3, 40)
        }

        title, level, reward = task_map[query.data]

        task_id = str(task_counter)
        task_counter += 1

        task = {
            "id": task_id,
            "title": title,
            "level": level,
            "reward_value": reward,
            "reward_type": "FIXED",
            "source": SOURCE_SYSTEM,
            "status": STATUS_SUBMITTED,
            "executor": username,
            "date": today()
        }

        tasks[task_id] = task
        save_task(task)

    elif query.data.startswith("task_user_"):
        task_id = query.data.split("_")[-1]
        task = tasks[task_id]

        task["status"] = STATUS_SUBMITTED
        update_task(task_id, "status", STATUS_SUBMITTED)

    await query.edit_message_text("Отправлено на проверку")

# ================= OFFER =================
async def offer_job(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username

    user_states[username] = "OFFER_TITLE"
    await update.message.reply_text("Название задания:")

# ================= ADMIN =================
async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != ADMIN_USERNAME:
        return

    for t in tasks.values():
        if t["status"] in [STATUS_SUBMITTED, STATUS_OFFERED]:

            text = f"{t['id']} - {t['title']}"
            if t["status"] == STATUS_OFFERED:
                text += "\n(ОФФЕР)"

            keyboard = [
                [
                    InlineKeyboardButton("✅", callback_data=f"approve_{t['id']}"),
                    InlineKeyboardButton("❌", callback_data=f"reject_{t['id']}")
                ]
            ]

            await update.message.reply_text(
                text,
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

        if task["status"] == STATUS_OFFERED:
            task["status"] = STATUS_AVAILABLE
            update_task(task_id, "status", STATUS_AVAILABLE)

            await query.edit_message_text(f"✅ Оффер принят: {task['title']}")
            return

        task["status"] = STATUS_APPROVED
        update_task(task_id, "status", STATUS_APPROVED)

        reward = task.get("reward_value", 0)
        add_money(username, reward, "TASK_REWARD", task["title"])

        if task.get("reward_type") == "FIXED" and task["title"] == "Математика":
            users[username]["bank_counter"] += 1
            if users[username]["bank_counter"] == 3:
                users[username]["bank_counter"] = 0
                add_money(username, 15, "MATH_BANK")

        msg = update_series(username)
        update_user(username)

        await query.edit_message_text(f"✅ {task['title']}")

        if msg:
            await query.message.reply_text(msg)

    else:
        task["status"] = STATUS_REJECTED
        update_task(task_id, "status", STATUS_REJECTED)

        await query.edit_message_text(f"❌ {task['title']}")

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
    if not username:
        return

    # ===== USER FSM =====
    if username in user_states:
        state = user_states[username]

        if state == "OFFER_TITLE":
            context.user_data["offer_title"] = update.message.text
            user_states[username] = "OFFER_DESC"
            await update.message.reply_text("Описание задания:")
            return

        elif state == "OFFER_DESC":
            context.user_data["offer_desc"] = update.message.text
            user_states[username] = "OFFER_REWARD"
            await update.message.reply_text("Награда (число):")
            return

        elif state == "OFFER_REWARD":
            global task_counter

            reward = float(update.message.text)

            task_id = str(task_counter)
            task_counter += 1

            task = {
                "id": task_id,
                "title": context.user_data["offer_title"],
                "description": context.user_data["offer_desc"],
                "source": SOURCE_USER,
                "reward_type": "FIXED",
                "reward_value": reward,
                "status": STATUS_OFFERED,
                "executor": username,
                "date": today()
            }

            tasks[task_id] = task
            save_task(task)

            user_states.pop(username)
            context.user_data.clear()

            await update.message.reply_text("Оффер отправлен на одобрение")
            return

    # ===== ADMIN FLOW =====
    if username == ADMIN_USERNAME and "admin_action" in context.user_data:
        step = context.user_data.get("step")
        target = context.user_data.get("target") or update.message.text

        if context.user_data["admin_action"] == "grade" and step != "grade_value":
            context.user_data["target"] = target
            context.user_data["step"] = "grade_value"
            await update.message.reply_text("Введи оценку:")
            return

        elif step == "grade_value":
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