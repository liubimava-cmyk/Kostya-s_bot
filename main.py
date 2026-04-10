import os
import json
import time
import asyncio
import threading
import datetime
import concurrent.futures
from collections import defaultdict

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    BotCommand,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# ================= SHEETS WRITE QUEUE =================
_sheets_queue = []
_sheets_lock = threading.Lock()
_sheets_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=3,
    thread_name_prefix="sheets",
)


def enqueue(func):
    with _sheets_lock:
        _sheets_queue.append(func)


async def _sheets_worker():
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(0.3)
        with _sheets_lock:
            batch = _sheets_queue.copy()
            _sheets_queue.clear()
        if batch:
            await loop.run_in_executor(
                _sheets_executor,
                lambda tasks=batch: [task() for task in tasks],
            )


# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
GOOGLE_SHEET_NAME = "Motivation_Log"
ADMIN_PASSWORD = "314159262"
ADMIN_ALLOWED_USERNAMES = ["Lbimova"]

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 8443))

ROLE_ADMIN = "ADMIN"
ROLE_USER = "USER"

STATUS_AVAILABLE = "AVAILABLE"
STATUS_OFFERED = "OFFERED"
STATUS_ARCHIVED = "ARCHIVED"
STATUS_REJECTED = "REJECTED"

STATUS_SUBMITTED = "SUBMITTED"
STATUS_APPROVED = "APPROVED"
STATUS_CANCELLED = "CANCELLED"

SOURCE_SYSTEM = "SYSTEM"
SOURCE_USER = "USER"

REWARD_FIXED = "FIXED"
REWARD_COEF = "COEF"

EVENT_TASK_REWARD = "TASK_REWARD"
EVENT_PAYMENT = "PAYMENT"
EVENT_SERIES_BONUS = "SERIES_BONUS"
EVENT_MATH_BANK = "MATH_BANK"
EVENT_SESSION_RESET = "SESSION_RESET"

STATE_ROLE_SELECT = "ROLE_SELECT"
STATE_ADMIN_PASSWORD = "ADMIN_PASSWORD"
STATE_OFFER_TITLE = "OFFER_TITLE"
STATE_OFFER_REWARD = "OFFER_REWARD"
STATE_INPUT_SCORE = "INPUT_SCORE"
STATE_ADMIN_ADD_TITLE = "ADMIN_ADD_TITLE"
STATE_ADMIN_ADD_REWARD = "ADMIN_ADD_REWARD"
STATE_ADMIN_PAY_USERNAME = "ADMIN_PAY_USERNAME"
STATE_ADMIN_PAY_AMOUNT = "ADMIN_PAY_AMOUNT"
STATE_ADMIN_END_SESSION_USERNAME = "ADMIN_END_SESSION_USERNAME"
STATE_ADMIN_END_SESSION_CONFIRM = "ADMIN_END_SESSION_CONFIRM"

SYSTEM_TASK_SEED = [
    {
        "level": "1",
        "title": "Посуда",
        "description": "",
        "source": SOURCE_SYSTEM,
        "reward_type": REWARD_FIXED,
        "reward_value": 1.5,
    },
    {
        "level": "1",
        "title": "Лоток",
        "description": "",
        "source": SOURCE_SYSTEM,
        "reward_type": REWARD_FIXED,
        "reward_value": 1.5,
    },
    {
        "level": "1",
        "title": "Мусор",
        "description": "",
        "source": SOURCE_SYSTEM,
        "reward_type": REWARD_FIXED,
        "reward_value": 1.5,
    },
    {
        "level": "1",
        "title": "Стол",
        "description": "",
        "source": SOURCE_SYSTEM,
        "reward_type": REWARD_FIXED,
        "reward_value": 1.5,
    },
    {
        "level": "1",
        "title": "Убрать часть комнаты",
        "description": "",
        "source": SOURCE_SYSTEM,
        "reward_type": REWARD_FIXED,
        "reward_value": 1.5,
    },
    {
        "level": "1",
        "title": "Магазин не ночью",
        "description": "",
        "source": SOURCE_SYSTEM,
        "reward_type": REWARD_FIXED,
        "reward_value": 1.5,
    },
    {
        "level": "1+",
        "title": "Не опоздать в школу",
        "description": "",
        "source": SOURCE_SYSTEM,
        "reward_type": REWARD_FIXED,
        "reward_value": 2.5,
    },
    {
        "level": "1++",
        "title": "Разбор темы по русскому",
        "description": "",
        "source": SOURCE_SYSTEM,
        "reward_type": REWARD_FIXED,
        "reward_value": 30.0,
    },
    {
        "level": "2",
        "title": "Русский",
        "description": "Введите баллы ЦТ",
        "source": SOURCE_SYSTEM,
        "reward_type": REWARD_COEF,
        "reward_value": 0.5,
    },
    {
        "level": "3",
        "title": "Английский",
        "description": "Введите баллы ЦТ",
        "source": SOURCE_SYSTEM,
        "reward_type": REWARD_COEF,
        "reward_value": 0.4,
    },
    {
        "level": "4",
        "title": "Математика",
        "description": "Введите баллы ЦТ",
        "source": SOURCE_SYSTEM,
        "reward_type": REWARD_FIXED,
        "reward_value": 0.0,
    },
]

MAIN_MENU_REPLY_KB = ReplyKeyboardMarkup(
    [[KeyboardButton("🏠 Главное меню"), KeyboardButton("Re/start")]],
    resize_keyboard=True,
    is_persistent=True,
)

SHEETS_SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

USERS_HEADERS = [
    "username",
    "series",
    "bank_counter",
    "last_date",
    "role",
    "session_start",
]
TASKS_HEADERS = [
    "id",
    "level",
    "title",
    "description",
    "source",
    "reward_type",
    "reward_value",
    "status",
    "author",
    "date",
]
DOINGS_HEADERS = [
    "id",
    "task",
    "title",
    "description",
    "source",
    "reward_type",
    "reward_value",
    "status",
    "executor",
    "date",
]
LEDGER_HEADERS = [
    "timestamp",
    "username",
    "amount",
    "event_type",
    "comment",
]


# ================= GOOGLE INIT =================
creds_json = os.environ.get("GOOGLE_SHEET_JSON_STR")
if not creds_json:
    raise ValueError("Переменная окружения GOOGLE_SHEET_JSON_STR не задана")

creds_dict = json.loads(creds_json)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SHEETS_SCOPE)
gc = gspread.authorize(creds)


def safe_append(ws, row):
    for _ in range(3):
        try:
            ws.append_row(row)
            return
        except Exception:
            time.sleep(1.2)


def get_or_create_worksheet(spreadsheet, title, headers):
    try:
        ws = spreadsheet.worksheet(title)
    except Exception:
        ws = spreadsheet.add_worksheet(title=title, rows="1000", cols=str(len(headers) + 3))
        ws.append_row(headers)
        return ws

    header_row = ws.row_values(1)
    if header_row != headers:
        raise ValueError(
            f"Лист '{title}' имеет неверные заголовки. Ожидается: {headers}. "
            f"Сейчас: {header_row}"
        )
    return ws


def init_sheets():
    global users_ws, tasks_ws, doings_ws, ledger_ws

    spreadsheet = gc.open(GOOGLE_SHEET_NAME)
    users_ws = get_or_create_worksheet(spreadsheet, "users", USERS_HEADERS)
    time.sleep(1.2)
    tasks_ws = get_or_create_worksheet(spreadsheet, "tasks", TASKS_HEADERS)
    time.sleep(1.2)
    doings_ws = get_or_create_worksheet(spreadsheet, "doings", DOINGS_HEADERS)
    time.sleep(1.2)
    ledger_ws = get_or_create_worksheet(spreadsheet, "ledger", LEDGER_HEADERS)


init_sheets()


# ================= DATA CONTAINERS =================
users = {}
tasks = {}
doings = {}
ledger = []
task_counter = 1
doing_counter = 1
insurance_used = defaultdict(bool)
user_states = {}


# ================= UTIL HELPERS =================
def today():
    return datetime.date.today()


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_date_safe(value):
    if not value:
        return None
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def parse_float_safe(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_username(value):
    if not value:
        return ""
    normalized = value.strip()
    if normalized.startswith("@"):
        normalized = normalized[1:]
    return normalized


def is_admin_allowed(username):
    return username in ADMIN_ALLOWED_USERNAMES


def clear_state(username, context):
    user_states.pop(username, None)
    context.user_data.pop("selected_task_id", None)
    context.user_data.pop("offer_title", None)
    context.user_data.pop("admin_task_title", None)
    context.user_data.pop("payment_target", None)
    context.user_data.pop("end_session_target", None)


def get_balance(username):
    total = 0.0
    for event in ledger:
        if event.get("username") == username:
            total += parse_float_safe(event.get("amount", 0))
    return total


def next_task_id():
    global task_counter
    value = str(task_counter)
    task_counter += 1
    return value


def next_doing_id():
    global doing_counter
    value = str(doing_counter)
    doing_counter += 1
    return value


# ================= LOAD / SAVE =================
def ensure_user(username):
    if username not in users:
        users[username] = {
            "series": 0,
            "bank_counter": 0,
            "last_date": None,
            "role": ROLE_USER,
            "session_start": today(),
        }
        save_user(username)
    return users[username]


def save_user(username):
    user = users[username]
    row = [
        username,
        user.get("series", 0),
        user.get("bank_counter", 0),
        user.get("last_date").isoformat() if user.get("last_date") else "",
        user.get("role", ROLE_USER),
        user.get("session_start").isoformat() if user.get("session_start") else "",
    ]

    def _write(uname=username, data=row):
        try:
            cell = users_ws.find(uname)
            users_ws.update(f"A{cell.row}:F{cell.row}", [data])
        except Exception:
            safe_append(users_ws, data)

    enqueue(_write)


def save_task(task_id):
    task = tasks[task_id]
    row = [
        task["id"],
        task.get("level", ""),
        task.get("title", ""),
        task.get("description", ""),
        task.get("source", ""),
        task.get("reward_type", ""),
        task.get("reward_value", 0),
        task.get("status", ""),
        task.get("author", ""),
        task.get("date", ""),
    ]

    def _write(tid=task_id, data=row):
        try:
            cell = tasks_ws.find(str(tid))
            tasks_ws.update(f"A{cell.row}:J{cell.row}", [data])
        except Exception:
            safe_append(tasks_ws, data)

    enqueue(_write)


def save_doing(doing_id):
    doing = doings[doing_id]
    row = [
        doing["id"],
        doing.get("task", ""),
        doing.get("title", ""),
        doing.get("description", ""),
        doing.get("source", ""),
        doing.get("reward_type", ""),
        doing.get("reward_value", 0),
        doing.get("status", ""),
        doing.get("executor", ""),
        doing.get("date", ""),
    ]

    def _write(did=doing_id, data=row):
        try:
            cell = doings_ws.find(str(did))
            doings_ws.update(f"A{cell.row}:J{cell.row}", [data])
        except Exception:
            safe_append(doings_ws, data)

    enqueue(_write)


def log_event(username, event_type, amount=0.0, comment=""):
    row = [now_str(), username, amount, event_type, comment]

    def _write(data=row):
        safe_append(ledger_ws, data)

    enqueue(_write)
    ledger.append(
        {
            "timestamp": row[0],
            "username": username,
            "amount": amount,
            "event_type": event_type,
            "comment": comment,
        }
    )


def load_data():
    global task_counter, doing_counter

    time.sleep(1.2)
    for row in users_ws.get_all_records():
        username = row.get("username")
        if not username:
            continue
        users[username] = {
            "series": int(row.get("series") or 0),
            "bank_counter": int(row.get("bank_counter") or 0),
            "last_date": parse_date_safe(row.get("last_date")),
            "role": row.get("role") or ROLE_USER,
            "session_start": parse_date_safe(row.get("session_start")) or today(),
        }

    time.sleep(1.2)
    for row in tasks_ws.get_all_records():
        task_id = str(row.get("id", "")).strip()
        if not task_id:
            continue
        tasks[task_id] = {
            "id": task_id,
            "level": str(row.get("level", "")).strip(),
            "title": row.get("title", ""),
            "description": row.get("description", ""),
            "source": row.get("source", ""),
            "reward_type": row.get("reward_type", ""),
            "reward_value": parse_float_safe(row.get("reward_value", 0)),
            "status": row.get("status", ""),
            "author": row.get("author", ""),
            "date": str(row.get("date", "")),
        }

    time.sleep(1.2)
    for row in doings_ws.get_all_records():
        doing_id = str(row.get("id", "")).strip()
        if not doing_id:
            continue
        doings[doing_id] = {
            "id": doing_id,
            "task": str(row.get("task", "")),
            "title": row.get("title", ""),
            "description": row.get("description", ""),
            "source": row.get("source", ""),
            "reward_type": row.get("reward_type", ""),
            "reward_value": parse_float_safe(row.get("reward_value", 0)),
            "status": row.get("status", ""),
            "executor": row.get("executor", ""),
            "date": str(row.get("date", "")),
        }

    time.sleep(1.2)
    rows = ledger_ws.get_all_records()
    ledger.extend(rows)

    task_ids = [int(task_id) for task_id in tasks if str(task_id).isdigit()]
    doing_ids = [int(doing_id) for doing_id in doings if str(doing_id).isdigit()]
    task_counter = (max(task_ids) + 1) if task_ids else 1
    doing_counter = (max(doing_ids) + 1) if doing_ids else 1


load_data()


# ================= BUSINESS HELPERS =================
def ensure_system_tasks_initialized():
    if tasks:
        return

    for item in SYSTEM_TASK_SEED:
        task_id = next_task_id()
        tasks[task_id] = {
            "id": task_id,
            "level": item["level"],
            "title": item["title"],
            "description": item["description"],
            "source": item["source"],
            "reward_type": item["reward_type"],
            "reward_value": item["reward_value"],
            "status": STATUS_AVAILABLE,
            "author": "SYSTEM",
            "date": str(today()),
        }
        save_task(task_id)


ensure_system_tasks_initialized()


def set_user_role(username, role):
    ensure_user(username)
    users[username]["role"] = role
    if not users[username].get("session_start"):
        users[username]["session_start"] = today()
    save_user(username)


def calculate_reward(task, score=None):
    level = task.get("level")
    reward_type = task.get("reward_type")
    reward_value = parse_float_safe(task.get("reward_value", 0))

    if level == "4":
        if score is None:
            raise ValueError("Для уровня 4 требуется score")
        return 15.0 if score <= 20 else 40.0

    if reward_type == REWARD_COEF:
        if score is None:
            raise ValueError("Для задания с коэффициентом требуется score")
        return float(score) * reward_value

    return reward_value


def create_doing_from_task(task_id, executor, score=None):
    if task_id not in tasks:
        raise ValueError("Задание не найдено")

    task = tasks[task_id]
    reward = calculate_reward(task, score=score)
    doing_id = next_doing_id()
    doings[doing_id] = {
        "id": doing_id,
        "task": task_id,
        "title": task.get("title", ""),
        "description": task.get("description", ""),
        "source": task.get("source", ""),
        "reward_type": task.get("reward_type", ""),
        "reward_value": reward,
        "status": STATUS_SUBMITTED,
        "executor": executor,
        "date": str(today()),
    }
    save_doing(doing_id)
    return doings[doing_id]


def update_series_on_approved_doing(username):
    user = ensure_user(username)
    last = user.get("last_date")
    insurance_message = None

    if last:
        diff = (today() - last).days
        if diff == 1:
            user["series"] += 1
        elif diff == 2 and not insurance_used[username]:
            insurance_used[username] = True
            user["last_date"] = today()
            save_user(username)
            insurance_message = (
                "🚨 СТРАХОВОЧНЫЙ ДЕНЬ ИСПОЛЬЗОВАН!\n"
                "Серия сохранена, дальше выполняй задания ежедневно."
            )
            return insurance_message
        else:
            user["series"] = 1
    else:
        user["series"] = 1

    user["last_date"] = today()

    if user["series"] == 5:
        log_event(username, EVENT_SERIES_BONUS, 10, "Бонус за 5 дней серии")
    if user["series"] == 9:
        log_event(username, EVENT_SERIES_BONUS, 25, "Бонус за 9 дней серии")

    save_user(username)
    return insurance_message


def apply_math_bank_if_needed(username, doing):
    task_id = str(doing.get("task", ""))
    task = tasks.get(task_id)
    if not task:
        return

    if task.get("level") != "4":
        return

    user = ensure_user(username)
    user["bank_counter"] = user.get("bank_counter", 0) + 1
    if user["bank_counter"] % 3 == 0:
        log_event(
            username,
            EVENT_MATH_BANK,
            15,
            f"Банк математики: {user['bank_counter']} выполнений уровня 4",
        )
    save_user(username)


def build_stats_text(target_username):
    user = users.get(target_username, {})
    session_start = user.get("session_start")
    session_start_str = session_start.strftime("%d.%m.%Y") if session_start else "—"
    series = user.get("series", 0)
    bank_counter = user.get("bank_counter", 0)
    balance = get_balance(target_username)

    approved_doings = []
    for doing in doings.values():
        if doing.get("executor") != target_username:
            continue
        if doing.get("status") != STATUS_APPROVED:
            continue
        doing_date = parse_date_safe(doing.get("date"))
        if session_start and doing_date and doing_date < session_start:
            continue
        approved_doings.append(doing)

    approved_doings.sort(key=lambda item: item.get("date", ""))

    payouts = []
    for event in ledger:
        if event.get("username") != target_username:
            continue
        if str(event.get("event_type", "")).upper() not in {EVENT_PAYMENT, "PAYOUT"}:
            continue
        event_date = parse_date_safe(str(event.get("timestamp", ""))[:10])
        if session_start and event_date and event_date < session_start:
            continue
        payouts.append(event)

    lines = [f"📊 Статистика @{target_username}"]
    lines.append(f"🗓 Начало сессии: {session_start_str}")
    lines.append(f"🔥 Серия: {series} дн.")
    lines.append("")
    lines.append("📋 Одобренные задания за текущую сессию:")

    if approved_doings:
        total_sum = 0.0
        for item in approved_doings:
            reward = parse_float_safe(item.get("reward_value", 0))
            total_sum += reward
            lines.append(
                f"  • {item.get('date', '')} — {item.get('title', '—')} — +{reward:.1f} р."
            )
        lines.append(
            f"  ▶ Итого: {len(approved_doings)} заданий, {total_sum:.1f} р."
        )
    else:
        lines.append("  Нет одобренных заданий в этой сессии")

    lines.append("")
    lines.append("💸 Выплаты за текущую сессию:")
    if payouts:
        total_paid = 0.0
        for event in payouts:
            amount = abs(parse_float_safe(event.get("amount", 0)))
            total_paid += amount
            lines.append(
                f"  • {str(event.get('timestamp', ''))[:10]} — {amount:.1f} р."
            )
        lines.append(f"  ▶ Итого: {len(payouts)} выплат, {total_paid:.1f} р.")
    else:
        lines.append("  Нет выплат в этой сессии")

    lines.append("")
    lines.append(f"💼 Остаток: {balance:.1f} р.")
    lines.append(f"📐 Банк математики: {bank_counter}")
    return "\n".join(lines)


def get_known_usernames():
    usernames = set(users.keys())
    usernames.update(doing.get("executor") for doing in doings.values() if doing.get("executor"))
    usernames.update(event.get("username") for event in ledger if event.get("username"))
    return sorted(user for user in usernames if user)


# ================= KEYBOARDS =================
def role_selection_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Администратор", callback_data="role_admin")],
            [InlineKeyboardButton("Пользователь", callback_data="role_user")],
        ]
    )


def user_menu_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Доступные задания", callback_data="user_tasks")],
            [InlineKeyboardButton("Справка", callback_data="help")],
            [InlineKeyboardButton("Предложить задание", callback_data="offer_job")],
            [InlineKeyboardButton("Статистика", callback_data="user_stats")],
        ]
    )


def admin_menu_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Непроверенные", callback_data="admin_pending")],
            [InlineKeyboardButton("Предложенные работы", callback_data="admin_offers")],
            [InlineKeyboardButton("Справка", callback_data="help")],
            [InlineKeyboardButton("Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton("Оплатить", callback_data="admin_pay")],
            [InlineKeyboardButton("Добавить задание", callback_data="admin_add_task")],
            [InlineKeyboardButton("Удалить задание", callback_data="admin_delete_task")],
            [InlineKeyboardButton("Прервать сессию", callback_data="admin_end_session")],
            [InlineKeyboardButton("В главное меню", callback_data="main_menu")],
        ]
    )


def back_to_main_menu_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("В главное меню", callback_data="main_menu")]]
    )


# ================= VIEWS =================
async def send_or_edit(update: Update, text: str, reply_markup=None):
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    ensure_user(username)
    role = users.get(username, {}).get("role", ROLE_USER)

    if role == ROLE_ADMIN:
        text = "Меню Администратора:"
        markup = admin_menu_keyboard()
    else:
        text = "Меню Пользователя:"
        markup = user_menu_keyboard()

    await send_or_edit(update, text, reply_markup=markup)


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Правила:\n"
        "1. Выполняй задания и отправляй их на проверку.\n"
        "2. За задания с баллами вводи неотрицательные значения.\n"
        "3. Серия обновляется после одобрения задания администратором.\n"
        "4. Бонусы серии: 5 дней = +10 р., 9 дней = +25 р.\n"
        "5. Банк математики: каждые 3 одобренных задания уровня 4 = +15 р.\n"
        "6. Re/start всегда запускает повторный выбор роли."
    )
    await send_or_edit(update, text, reply_markup=back_to_main_menu_keyboard())


# ================= START / ROLE =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if not username:
        await update.message.reply_text("У тебя не задан username в Telegram.")
        return

    ensure_user(username)
    clear_state(username, context)
    user_states[username] = STATE_ROLE_SELECT

    await update.message.reply_text(
        "Используй кнопку ниже для быстрого возврата в меню:",
        reply_markup=MAIN_MENU_REPLY_KB,
    )
    await update.message.reply_text(
        "Выбери роль:",
        reply_markup=role_selection_keyboard(),
    )


# ================= USER FLOWS =================
def get_available_tasks_by_level():
    grouped = defaultdict(list)
    for task in tasks.values():
        if task.get("status") == STATUS_AVAILABLE:
            grouped[task.get("level", "")].append(task)
    for level in grouped:
        grouped[level].sort(key=lambda item: (item.get("title", ""), item.get("id", "")))
    return grouped


async def show_user_levels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    grouped = get_available_tasks_by_level()
    levels = [level for level in ["1", "1+", "1++", "2", "3", "4"] if grouped.get(level)]

    if not levels:
        await send_or_edit(
            update,
            "Нет доступных заданий.",
            reply_markup=back_to_main_menu_keyboard(),
        )
        return

    keyboard = [[InlineKeyboardButton(f"Уровень {level}", callback_data=f"tasks_level_{level}")] for level in levels]
    keyboard.append([InlineKeyboardButton("В главное меню", callback_data="main_menu")])
    await send_or_edit(
        update,
        "Выбери уровень:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_tasks_for_level(update: Update, context: ContextTypes.DEFAULT_TYPE, level: str):
    grouped = get_available_tasks_by_level()
    level_tasks = grouped.get(level, [])
    if not level_tasks:
        await send_or_edit(
            update,
            f"Для уровня {level} нет доступных заданий.",
            reply_markup=back_to_main_menu_keyboard(),
        )
        return

    buttons = []
    for task in level_tasks:
        reward_type = task.get("reward_type")
        reward_value = parse_float_safe(task.get("reward_value", 0))
        if level == "4":
            label = f"{task['title']} — 15/40 р."
        elif reward_type == REWARD_COEF:
            label = f"{task['title']} — коэф. {reward_value}"
        else:
            label = f"{task['title']} — {reward_value:.1f} р."
        buttons.append([InlineKeyboardButton(label, callback_data=f"task_select_{task['id']}")])

    buttons.append([InlineKeyboardButton("← Назад", callback_data="user_tasks")])
    buttons.append([InlineKeyboardButton("В главное меню", callback_data="main_menu")])
    await send_or_edit(
        update,
        f"Задания уровня {level}:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def handle_task_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, task_id: str):
    username = update.effective_user.username
    task = tasks.get(task_id)
    if not task or task.get("status") != STATUS_AVAILABLE:
        await update.callback_query.answer("Задание недоступно")
        return

    level = task.get("level")
    if level in {"2", "3", "4"}:
        clear_state(username, context)
        user_states[username] = STATE_INPUT_SCORE
        context.user_data["selected_task_id"] = task_id
        await update.callback_query.message.reply_text(
            f"Введи баллы для задания «{task.get('title', '')}»:"
        )
        return

    doing = create_doing_from_task(task_id, username)
    clear_state(username, context)
    await update.callback_query.message.reply_text(
        f"Задание отправлено на проверку: {doing['title']} — {doing['reward_value']:.1f} р."
    )


async def show_user_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    text = build_stats_text(username)
    await send_or_edit(update, text[:4096], reply_markup=back_to_main_menu_keyboard())


# ================= ADMIN FLOWS =================
async def show_admin_pending_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending_doings = [item for item in doings.values() if item.get("status") == STATUS_SUBMITTED]
    if not pending_doings:
        await send_or_edit(
            update,
            "Нет непроверенных заданий.",
            reply_markup=admin_menu_keyboard(),
        )
        return

    executors = sorted({item.get("executor") for item in pending_doings if item.get("executor")})
    text_lines = ["Выбери пользователя для проверки:"]
    buttons = []
    for executor in executors:
        count = sum(1 for item in pending_doings if item.get("executor") == executor)
        text_lines.append(f"@{executor}: {count} шт.")
        buttons.append([InlineKeyboardButton(f"@{executor}", callback_data=f"admin_pending_user_{executor}")])

    buttons.append([InlineKeyboardButton("В главное меню", callback_data="main_menu")])
    await send_or_edit(
        update,
        "\n".join(text_lines),
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def show_admin_pending_for_user(update: Update, context: ContextTypes.DEFAULT_TYPE, target: str):
    target_doings = [
        item for item in doings.values()
        if item.get("executor") == target and item.get("status") == STATUS_SUBMITTED
    ]
    if not target_doings:
        await send_or_edit(
            update,
            f"У @{target} нет непроверенных заданий.",
            reply_markup=admin_menu_keyboard(),
        )
        return

    target_doings.sort(key=lambda item: (item.get("date", ""), item.get("id", "")))
    lines = [f"@{target} — непроверенные задания:", ""]
    buttons = []
    for index, item in enumerate(target_doings, start=1):
        reward = parse_float_safe(item.get("reward_value", 0))
        lines.append(
            f"{index}. {item.get('date', '')} / {item.get('title', '—')} — {reward:.1f} р."
        )
        buttons.append([
            InlineKeyboardButton(str(index), callback_data=f"admin_doing_action_{item['id']}")
        ])

    buttons.append([InlineKeyboardButton("← Назад", callback_data="admin_pending")])
    buttons.append([InlineKeyboardButton("В главное меню", callback_data="main_menu")])
    await send_or_edit(
        update,
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def show_admin_doing_action(update: Update, context: ContextTypes.DEFAULT_TYPE, doing_id: str):
    doing = doings.get(doing_id)
    if not doing:
        await update.callback_query.answer("Выполнение не найдено")
        return

    reward = parse_float_safe(doing.get("reward_value", 0))
    text = (
        f"Задание: {doing.get('title', '—')}\n"
        f"Исполнитель: @{doing.get('executor', '?')}\n"
        f"Дата: {doing.get('date', '')}\n"
        f"Стоимость: {reward:.1f} р.\n\n"
        "Принять или отклонить?"
    )
    buttons = [
        [
            InlineKeyboardButton("✅ Принять", callback_data=f"admin_approve_doing_{doing_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"admin_reject_doing_{doing_id}"),
        ],
        [
            InlineKeyboardButton(
                "← Назад",
                callback_data=f"admin_pending_user_{doing.get('executor', '')}",
            ),
            InlineKeyboardButton("В главное меню", callback_data="main_menu"),
        ],
    ]
    await send_or_edit(update, text, reply_markup=InlineKeyboardMarkup(buttons))


async def approve_doing(update: Update, context: ContextTypes.DEFAULT_TYPE, doing_id: str):
    doing = doings.get(doing_id)
    if not doing:
        await update.callback_query.answer("Выполнение не найдено")
        return
    if doing.get("status") != STATUS_SUBMITTED:
        await update.callback_query.answer("Это выполнение уже обработано")
        return

    doing["status"] = STATUS_APPROVED
    save_doing(doing_id)

    username = doing.get("executor")
    reward = parse_float_safe(doing.get("reward_value", 0))
    log_event(username, EVENT_TASK_REWARD, reward, f"Одобрено: {doing.get('title', '')}")
    update_series_on_approved_doing(username)
    apply_math_bank_if_needed(username, doing)

    await update.callback_query.answer("Задание одобрено")
    await show_admin_pending_users(update, context)


async def reject_doing(update: Update, context: ContextTypes.DEFAULT_TYPE, doing_id: str):
    doing = doings.get(doing_id)
    if not doing:
        await update.callback_query.answer("Выполнение не найдено")
        return
    if doing.get("status") != STATUS_SUBMITTED:
        await update.callback_query.answer("Это выполнение уже обработано")
        return

    doing["status"] = STATUS_REJECTED
    save_doing(doing_id)
    await update.callback_query.answer("Задание отклонено")
    await show_admin_pending_users(update, context)


async def show_admin_offers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    offers = [task for task in tasks.values() if task.get("status") == STATUS_OFFERED]
    if not offers:
        await send_or_edit(
            update,
            "Нет предложенных заданий.",
            reply_markup=admin_menu_keyboard(),
        )
        return

    offers.sort(key=lambda item: (item.get("date", ""), item.get("id", "")))
    lines = ["Предложенные задания:"]
    buttons = []
    for item in offers:
        reward = parse_float_safe(item.get("reward_value", 0))
        lines.append(f"{item['id']}. {item.get('title', '—')} — {reward:.1f} р.")
        buttons.append([
            InlineKeyboardButton(
                f"Одобрить {item['id']}",
                callback_data=f"admin_approve_offer_{item['id']}",
            ),
            InlineKeyboardButton(
                f"Отклонить {item['id']}",
                callback_data=f"admin_reject_offer_{item['id']}",
            ),
        ])

    buttons.append([InlineKeyboardButton("В главное меню", callback_data="main_menu")])
    await send_or_edit(update, "\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))


async def show_admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    known_users = [user for user in get_known_usernames() if user]
    if not known_users:
        await send_or_edit(
            update,
            "Нет пользователей для просмотра статистики.",
            reply_markup=admin_menu_keyboard(),
        )
        return

    buttons = [[InlineKeyboardButton(f"@{user}", callback_data=f"admin_stats_user_{user}")] for user in known_users]
    buttons.append([InlineKeyboardButton("В главное меню", callback_data="main_menu")])
    await send_or_edit(update, "Выбери пользователя:", reply_markup=InlineKeyboardMarkup(buttons))


async def show_admin_delete_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    available_tasks = [task for task in tasks.values() if task.get("status") == STATUS_AVAILABLE]
    if not available_tasks:
        await send_or_edit(
            update,
            "Нет доступных заданий для удаления.",
            reply_markup=admin_menu_keyboard(),
        )
        return

    available_tasks.sort(key=lambda item: (item.get("level", ""), item.get("title", ""), item.get("id", "")))
    lines = ["Выбери задание для архивации:"]
    buttons = []
    for item in available_tasks:
        reward = parse_float_safe(item.get("reward_value", 0))
        if item.get("level") == "4":
            reward_text = "15/40 р."
        elif item.get("reward_type") == REWARD_COEF:
            reward_text = f"коэф. {reward:.1f}"
        else:
            reward_text = f"{reward:.1f} р."
        lines.append(f"{item['id']}. [{item.get('level', '')}] {item.get('title', '—')} — {reward_text}")
        buttons.append([
            InlineKeyboardButton(
                f"Удалить {item['id']}",
                callback_data=f"admin_archive_task_{item['id']}",
            )
        ])

    buttons.append([InlineKeyboardButton("В главное меню", callback_data="main_menu")])
    await send_or_edit(update, "\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))


# ================= TEXT HANDLER =================
async def global_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    text = (update.message.text or "").strip()
    ensure_user(username)

    if text == "🏠 Главное меню":
        clear_state(username, context)
        await show_main_menu(update, context)
        return

    if text == "Re/start":
        clear_state(username, context)
        await start(update, context)
        return

    state = user_states.get(username)

    if state == STATE_ADMIN_PASSWORD:
        if text == ADMIN_PASSWORD:
            set_user_role(username, ROLE_ADMIN)
            clear_state(username, context)
            await update.message.reply_text("Роль Администратор активирована.")
            await show_main_menu(update, context)
        else:
            await update.message.reply_text(
                "Неверный пароль. Введи пароль ещё раз или нажми Re/start."
            )
        return

    if state == STATE_OFFER_TITLE:
        context.user_data["offer_title"] = text
        user_states[username] = STATE_OFFER_REWARD
        await update.message.reply_text("Укажи награду за задание в рублях:")
        return

    if state == STATE_OFFER_REWARD:
        reward = parse_float_safe(text, default=None)
        if reward is None or reward < 0:
            await update.message.reply_text("Введите корректное неотрицательное число.")
            return

        task_id = next_task_id()
        tasks[task_id] = {
            "id": task_id,
            "level": "USER",
            "title": context.user_data.get("offer_title", "Без названия"),
            "description": "",
            "source": SOURCE_USER,
            "reward_type": REWARD_FIXED,
            "reward_value": reward,
            "status": STATUS_OFFERED,
            "author": username,
            "date": str(today()),
        }
        save_task(task_id)
        clear_state(username, context)
        await update.message.reply_text("Предложение задания отправлено администратору.")
        return

    if state == STATE_INPUT_SCORE:
        task_id = context.user_data.get("selected_task_id")
        score = parse_float_safe(text, default=None)
        if score is None:
            await update.message.reply_text("Введите число.")
            return
        if score < 0:
            await update.message.reply_text("Баллы не могут быть отрицательными.")
            return
        try:
            doing = create_doing_from_task(task_id, username, score=score)
        except ValueError as exc:
            await update.message.reply_text(str(exc))
            return

        clear_state(username, context)
        await update.message.reply_text(
            f"Задание отправлено на проверку: {doing['title']} — {doing['reward_value']:.1f} р."
        )
        return

    if state == STATE_ADMIN_ADD_TITLE:
        context.user_data["admin_task_title"] = text
        user_states[username] = STATE_ADMIN_ADD_REWARD
        await update.message.reply_text("Укажи награду в рублях:")
        return

    if state == STATE_ADMIN_ADD_REWARD:
        reward = parse_float_safe(text, default=None)
        if reward is None or reward < 0:
            await update.message.reply_text("Введите корректное неотрицательное число.")
            return

        task_id = next_task_id()
        tasks[task_id] = {
            "id": task_id,
            "level": "USER",
            "title": context.user_data.get("admin_task_title", "Без названия"),
            "description": "",
            "source": SOURCE_SYSTEM,
            "reward_type": REWARD_FIXED,
            "reward_value": reward,
            "status": STATUS_AVAILABLE,
            "author": username,
            "date": str(today()),
        }
        save_task(task_id)
        clear_state(username, context)
        await update.message.reply_text("Новое задание добавлено.")
        return

    if state == STATE_ADMIN_PAY_USERNAME:
        target = normalize_username(text)
        if target not in get_known_usernames():
            await update.message.reply_text("Пользователь не найден. Введи @username ещё раз.")
            return

        context.user_data["payment_target"] = target
        user_states[username] = STATE_ADMIN_PAY_AMOUNT
        await update.message.reply_text(f"Введи сумму выплаты для @{target}:")
        return

    if state == STATE_ADMIN_PAY_AMOUNT:
        target = context.user_data.get("payment_target")
        amount = parse_float_safe(text, default=None)
        if amount is None or amount < 0:
            await update.message.reply_text("Введите корректное неотрицательное число.")
            return

        log_event(target, EVENT_PAYMENT, -amount, "Выплата наличных")
        clear_state(username, context)
        await update.message.reply_text(f"Выплата @{target}: {amount:.1f} р. записана.")
        return

    if state == STATE_ADMIN_END_SESSION_USERNAME:
        target = normalize_username(text)
        if target not in users:
            await update.message.reply_text("Пользователь не найден в users. Введи @username ещё раз.")
            return

        target_user = users[target]
        session_start = target_user.get("session_start")
        last_date = target_user.get("last_date")
        context.user_data["end_session_target"] = target
        user_states[username] = STATE_ADMIN_END_SESSION_CONFIRM

        session_start_str = session_start.strftime("%d.%m.%Y") if session_start else "—"
        last_date_str = last_date.strftime("%d.%m.%Y") if last_date else "—"
        await update.message.reply_text(
            f"Подтверди завершение сессии для @{target}:\n"
            f"Серия: {target_user.get('series', 0)}\n"
            f"Начало сессии: {session_start_str}\n"
            f"Последнее задание: {last_date_str}\n"
            f"Баланс не изменится.\n\n"
            f"Напиши ДА для подтверждения или отправь любое другое сообщение для отмены."
        )
        return

    if state == STATE_ADMIN_END_SESSION_CONFIRM:
        target = context.user_data.get("end_session_target")
        if text != "ДА":
            clear_state(username, context)
            await update.message.reply_text("Завершение сессии отменено.")
            return

        ensure_user(target)
        users[target]["series"] = 0
        users[target]["bank_counter"] = 0
        users[target]["last_date"] = None
        users[target]["session_start"] = today()
        insurance_used[target] = False
        save_user(target)
        log_event(target, EVENT_SESSION_RESET, 0, "Сессия сброшена администратором")
        clear_state(username, context)
        await update.message.reply_text(f"Сессия пользователя @{target} успешно сброшена.")
        return

    await update.message.reply_text("Не понял сообщение. Используй меню или Re/start.")


# ================= CALLBACK HANDLER =================
async def global_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    username = query.from_user.username
    ensure_user(username)

    if data == "main_menu":
        clear_state(username, context)
        await show_main_menu(update, context)
        return

    if data == "help":
        await show_help(update, context)
        return

    if data == "role_user":
        set_user_role(username, ROLE_USER)
        clear_state(username, context)
        await query.message.reply_text("Роль Пользователь активирована.")
        await show_main_menu(update, context)
        return

    if data == "role_admin":
        if not is_admin_allowed(username):
            await query.message.reply_text("У тебя нет доступа к роли Администратор.")
            return
        clear_state(username, context)
        user_states[username] = STATE_ADMIN_PASSWORD
        await query.message.reply_text("Введи пароль администратора:")
        return

    if data == "user_tasks":
        await show_user_levels(update, context)
        return

    if data.startswith("tasks_level_"):
        level = data.replace("tasks_level_", "", 1)
        await show_tasks_for_level(update, context, level)
        return

    if data.startswith("task_select_"):
        task_id = data.replace("task_select_", "", 1)
        await handle_task_selection(update, context, task_id)
        return

    if data == "offer_job":
        clear_state(username, context)
        user_states[username] = STATE_OFFER_TITLE
        await query.message.reply_text("Введи название предлагаемого задания:")
        return

    if data == "user_stats":
        await show_user_stats(update, context)
        return

    if data == "admin_pending":
        await show_admin_pending_users(update, context)
        return

    if data.startswith("admin_pending_user_"):
        target = data.replace("admin_pending_user_", "", 1)
        await show_admin_pending_for_user(update, context, target)
        return

    if data.startswith("admin_doing_action_"):
        doing_id = data.replace("admin_doing_action_", "", 1)
        await show_admin_doing_action(update, context, doing_id)
        return

    if data.startswith("admin_approve_doing_"):
        doing_id = data.replace("admin_approve_doing_", "", 1)
        await approve_doing(update, context, doing_id)
        return

    if data.startswith("admin_reject_doing_"):
        doing_id = data.replace("admin_reject_doing_", "", 1)
        await reject_doing(update, context, doing_id)
        return

    if data == "admin_offers":
        await show_admin_offers(update, context)
        return

    if data.startswith("admin_approve_offer_"):
        task_id = data.replace("admin_approve_offer_", "", 1)
        if task_id in tasks:
            tasks[task_id]["status"] = STATUS_AVAILABLE
            save_task(task_id)
        await show_admin_offers(update, context)
        return

    if data.startswith("admin_reject_offer_"):
        task_id = data.replace("admin_reject_offer_", "", 1)
        if task_id in tasks:
            tasks[task_id]["status"] = STATUS_REJECTED
            save_task(task_id)
        await show_admin_offers(update, context)
        return

    if data == "admin_stats":
        await show_admin_stats(update, context)
        return

    if data.startswith("admin_stats_user_"):
        target = data.replace("admin_stats_user_", "", 1)
        text = build_stats_text(target)
        markup = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("← Назад", callback_data="admin_stats")],
                [InlineKeyboardButton("В главное меню", callback_data="main_menu")],
            ]
        )
        await send_or_edit(update, text[:4096], reply_markup=markup)
        return

    if data == "admin_pay":
        clear_state(username, context)
        user_states[username] = STATE_ADMIN_PAY_USERNAME
        await query.message.reply_text("Введи @username пользователя для выплаты:")
        return

    if data == "admin_add_task":
        clear_state(username, context)
        user_states[username] = STATE_ADMIN_ADD_TITLE
        await query.message.reply_text("Введи название нового задания:")
        return

    if data == "admin_delete_task":
        await show_admin_delete_tasks(update, context)
        return

    if data.startswith("admin_archive_task_"):
        task_id = data.replace("admin_archive_task_", "", 1)
        if task_id in tasks and tasks[task_id].get("status") == STATUS_AVAILABLE:
            tasks[task_id]["status"] = STATUS_ARCHIVED
            save_task(task_id)
        await show_admin_delete_tasks(update, context)
        return

    if data == "admin_end_session":
        clear_state(username, context)
        user_states[username] = STATE_ADMIN_END_SESSION_USERNAME
        await query.message.reply_text("Введи @username пользователя для завершения сессии:")
        return


# ================= POST INIT =================
async def post_init(application):
    asyncio.create_task(_sheets_worker())
    await application.bot.set_my_commands([
        BotCommand("start", "Запустить / сменить роль"),
    ])
    print("[Queue] Sheets write worker started")


# ================= BOOTSTRAP =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(global_query_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_text_handler))

    if WEBHOOK_URL:
        print(f"[Webhook] port={PORT} url={WEBHOOK_URL}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
        )
    else:
        print("[Polling] Бот запущен в режиме polling...")
        app.run_polling()
