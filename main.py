import os
import datetime
import json
import time
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
ADMIN_USERNAME = "Lbimova"
KOSTYA_USERNAMES = ["kxstik_smerch", "babushka_ira_lub"]

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

# ================= CONSTANTS =================
STATUS_AVAILABLE = "AVAILABLE"
STATUS_OFFERED = "OFFERED"
STATUS_SUBMITTED = "SUBMITTED"
STATUS_APPROVED = "APPROVED"
STATUS_REJECTED = "REJECTED"

SOURCE_SYSTEM = "SYSTEM"
SOURCE_USER = "USER"

# ================= DATA =================
users = {}
tasks = {}
task_counter = 1
ledger = []

insurance_used = defaultdict(bool)
daily_levels = defaultdict(list)
user_states = {}

# ================= HELPERS =================
def today():
    return datetime.date.today()

def safe_append(ws, row):
    for _ in range(3):
        try:
            ws.append_row(row)
            return
        except:
            time.sleep(1)

def log_event(username, event_type, amount=0, balance=0, comment=""):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_append(ledger_ws, [now, username, amount, event_type, comment])

def get_balance(username):
    return sum(x["amount"] for x in ledger if x["username"] == username)

def approved_today(username):
    return [
        t for t in tasks.values()
        if t["executor"] == username and t["status"] == STATUS_APPROVED and t["date"] == today()
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
    update_user(username)

def update_series(username):
    if username not in users:
        return None
    user = users[username]
    last = user.get("last_date")
    msg = None
    if last:
        diff = (today() - last).days
        if diff == 1:
            user["series"] += 1
        elif diff == 2 and not insurance_used[username]:
            insurance_used[username] = True
            last_day = today() + datetime.timedelta(days=14)
            user["series"] = 1
            msg = f"🚨 СТРАХОВОЧНЫЙ ДЕНЬ ИСПОЛЬЗОВАН!\nДо {last_day.strftime('%d.%m')} выполняй задания каждый день!"
        else:
            user["series"] = 1
    else:
        user["series"] = 1
    user["last_date"] = today()
    if user["series"] == 5:
        add_money(username, 10, "SERIES_BONUS")
    if user["series"] == 9:
        add_money(username, 25, "SERIES_BONUS")
    return msg

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
    col_map = {"status":7, "executor":8}
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

def load_data():
    global tasks, users, ledger, task_counter
    tasks, users, ledger = {}, {}, []

    # TASKS
    rows = tasks_ws.get_all_records()
    for r in rows:
        tasks[r["id"]] = r

    # USERS
    rows = users_ws.get_all_records()
    for r in rows:
        users[r["username"]] = {
            "series": int(r["series"]),
            "bank_counter": int(r["bank_counter"]),
            "last_date": datetime.date.fromisoformat(r["last_date"]) if r["last_date"] else None
        }

    # LEDGER
    rows = ledger_ws.get_all_records()
    for r in rows:
        ledger.append(r)

    # counter
    if tasks:
        task_counter = max(int(k) for k in tasks.keys()) + 1
    else:
        task_counter = 1

load_data()
# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if not username:
        await update.message.reply_text("Ваш username не определён")
        return

    # Инициализация пользователя
    if username not in users:
        users[username] = {"series":0, "bank_counter":0, "last_date":None}
        save_user(username)

    # Определяем роль
    role = "GUEST"
    if username == ADMIN_USERNAME:
        role = "MAMA"
    elif username in KOSTYA_USERNAMES:
        role = "KOSTYA"
    context.user_data["role"] = role

    # Главное меню
    keyboard = [
        [InlineKeyboardButton("Начать сессию", callback_data="start_session")],
        [InlineKeyboardButton("Справка", callback_data="help")],
        [InlineKeyboardButton("Доступные задания", callback_data="tasks_list")]
    ]
    if role == "KOSTYA":
        keyboard.append([InlineKeyboardButton("Предложить задание", callback_data="offer_task")])
        keyboard.append([InlineKeyboardButton("Статистика", callback_data="stats")])
    elif role == "MAMA":
        keyboard.append([InlineKeyboardButton("Непроверенные", callback_data="pending_review")])
        keyboard.append([InlineKeyboardButton("Предложенные работы", callback_data="offers_review")])
        keyboard.append([InlineKeyboardButton("Статистика", callback_data="stats")])
        keyboard.append([InlineKeyboardButton("Оплатить", callback_data="pay_kostya")])

    await update.message.reply_text(
        f"Бот готов. Роль: {role}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================= CALLBACKS =================
async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    username = query.from_user.username
    role = context.user_data.get("role", "GUEST")

    # ===== Справка =====
    if query.data == "help":
        help_text = (
            "Правила:\n"
            "- Делай задания каждый день, чтобы сохранить серию.\n"
            "- Серии дают бонусы на 5-й и 9-й день.\n"
            "- Костя может предлагать задания, Мама их одобряет.\n"
            "- Каждое задание приносит награду.\n"
            "- Статистика за последние 14 дней видна через кнопку Статистика."
        )
        await query.edit_message_text(help_text)
        return

    # ===== Начать сессию =====
    if query.data == "start_session":
        if role == "MAMA":
            await show_mama_offers(username, query)
        elif role == "KOSTYA":
            await query.edit_message_text("Привет, Костя! Выбирай действие через кнопки меню.")
        else:
            await query.edit_message_text("Привет, Гость! Выбирай задания через кнопки меню.")
        return

    # ===== Доступные задания =====
    if query.data == "tasks_list":
        await tasks_cmd(update, context)
        return

    # ===== Кнопка Предложить задание для Кости =====
    if query.data == "offer_task" and role == "KOSTYA":
        user_states[username] = "OFFER_TITLE"
        await query.edit_message_text("Название задания:")
        return

    # ===== Кнопка Статистика =====
    if query.data == "stats":
        await show_stats(username, role, query)
        return

    # ===== Кнопки Мамы =====
    if role == "MAMA":
        if query.data == "pending_review":
            await show_pending_tasks(username, query)
            return
        if query.data == "offers_review":
            await show_kostya_offers(username, query)
            return
        if query.data == "pay_kostya":
            user_states[username] = "PAY_KOSTYA"
            await query.edit_message_text("Введите сумму оплаты Косте (может быть отрицательной):")
            return

# ================= MAMA FLOWS =================
async def show_mama_offers(username, query):
    # Перечень предложенных Костей заданий
    offer_list = [
        t for t in tasks.values() if t["source"] == SOURCE_USER and t["status"] == STATUS_OFFERED
    ]
    if offer_list:
        texts = []
        for t in offer_list:
            texts.append(f"{t['id']}. {t['title']} — предложено {t['reward_value']}")
        await query.edit_message_text("Предложенные Костей задания:\n" + "\n".join(texts))
        # Далее Мама вводит номер и стоимость через текст "номер 00"
    else:
        await query.edit_message_text("Нет предложенных Костей заданий.")

async def show_pending_tasks(username, query):
    pending = [
        t for t in tasks.values()
        if t["status"] == STATUS_SUBMITTED
    ]
    if pending:
        texts = []
        for t in pending:
            texts.append(f"{t['id']}. {t['title']} — {t['reward_value']}")
        await query.edit_message_text("Выполненные задания, ожидающие принятия:\n" + "\n".join(texts))
    else:
        await query.edit_message_text("Нет заданий для проверки.")

async def show_kostya_offers(username, query):
    offers = [
        t for t in tasks.values()
        if t["source"] == SOURCE_USER
    ]
    if offers:
        texts = []
        for t in offers:
            texts.append(f"{t['id']}. {t['title']} — {t['reward_value']} (Статус: {t['status']})")
        await query.edit_message_text("Предложенные работы Кости:\n" + "\n".join(texts))
    else:
        await query.edit_message_text("Костя ещё не предложил задания.")

async def show_stats(username, role, query):
    cutoff = today() - datetime.timedelta(days=14)
    relevant_ledger = [x for x in ledger if datetime.date.fromisoformat(x.get("date", str(today()))) >= cutoff]
    total = sum(x["amount"] for x in relevant_ledger if x["username"] == username)
    await query.edit_message_text(f"Статистика за последние 14 дней:\nЗаработано: {total}")

# ================= TEXT HANDLER =================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if not username:
        return

    # ===== USER FSM =====
    if username in user_states:
        state = user_states[username]

        # 1. название оффера
        if state == "OFFER_TITLE":
            context.user_data["offer_title"] = update.message.text
            user_states[username] = "OFFER_DESC"
            await update.message.reply_text("Описание задания:")
            return

        # 2. описание
        elif state == "OFFER_DESC":
            context.user_data["offer_desc"] = update.message.text
            user_states[username] = "OFFER_REWARD"
            await update.message.reply_text("Награда (число):")
            return

        # 3. награда
        elif state == "OFFER_REWARD":
            global task_counter
            reward = float(update.message.text)
            task_id = str(task_counter)
            task_counter += 1
            tasks[task_id] = {
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
            save_task(tasks[task_id])
            user_states.pop(username)
            context.user_data.clear()
            await update.message.reply_text("Оффер отправлен на одобрение Мамой")
            return

        # ===== MAMA ввод стоимости =====
        elif state == "MAMA_APPROVE":
            # ожидаем ввод "номер 00"
            try:
                task_id_str, new_val = update.message.text.strip().split()
                task_id = str(task_id_str)
                new_val = float(new_val)
                if task_id in tasks:
                    tasks[task_id]["status"] = STATUS_AVAILABLE
                    tasks[task_id]["reward_value"] = new_val
                    update_task(task_id, "status", STATUS_AVAILABLE)
                    update_task(task_id, "executor", tasks[task_id]["executor"])
                    await update.message.reply_text(f"Задание {task_id} одобрено и добавлено в доступные")
            except:
                await update.message.reply_text("Ошибка формата. Используй 'номер 00'")
            user_states.pop(username)
            return

        # ===== Оплата Мамой Косте =====
        elif state == "PAY_KOSTYA":
            try:
                amount = float(update.message.text)
                add_money("kxstik_smerch", amount, "PAYMENT_BY_MAMA", "Оплата Мамой")
                add_money("babushka_ira_lub", amount, "PAYMENT_BY_MAMA", "Оплата Мамой")
                await update.message.reply_text(f"Оплата Косте проведена: {amount}")
            except:
                await update.message.reply_text("Ошибка ввода. Введите число.")
            user_states.pop(username)
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

# ================= TASK SELECTION =================
async def tasks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    username = update.effective_user.username

    # системные
    keyboard.extend([
        [InlineKeyboardButton("Посуда (1.5)", callback_data="task_sys_1")],
        [InlineKeyboardButton("Мусор (1.5)", callback_data="task_sys_2")],
        [InlineKeyboardButton("Математика", callback_data="task_sys_3")]
    ])

    # доступные пользовательские задания
    for t in tasks.values():
        if t["status"] == STATUS_AVAILABLE:
            keyboard.append([InlineKeyboardButton(f"{t['title']} ({t['reward_value']})", callback_data=f"task_user_{t['id']}")])

    await update.effective_message.reply_text("Выбери задание:", reply_markup=InlineKeyboardMarkup(keyboard))

async def task_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global task_counter
    query = update.callback_query
    await query.answer()
    username = query.from_user.username

    if query.data.startswith("task_sys_"):
        task_map = {
            "task_sys_1": ("Посуда", 1, 1.5),
            "task_sys_2": ("Мусор", 1, 1.5),
            "task_sys_3": ("Математика", 3, 40)
        }
        title, level, reward = task_map[query.data]
        task_id = str(task_counter)
        task_counter += 1
        tasks[task_id] = {
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
        save_task(tasks[task_id])

    elif query.data.startswith("task_user_"):
        task_id = query.data.split("_")[-1]
        task = tasks[task_id]
        task["status"] = STATUS_SUBMITTED
        update_task(task_id, "status", STATUS_SUBMITTED)

    await query.edit_message_text(f"Отправлено на проверку: {tasks[task_id]['title']}")

# ================= RUN =================
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(main_menu_handler))
app.add_handler(CallbackQueryHandler(task_select, pattern="task_"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

app.run_polling()