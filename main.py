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
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 8443))

ROLE_ADMIN = "ADMIN"
ROLE_USER = "USER"

STATUS_AVAILABLE = "AVAILABLE"
STATUS_OFFERED = "OFFERED"
STATUS_ARCHIVED = "ARCHIVED"
STATUS_REJECTED = "REJECTED"

DOING_STATUS_SUBMITTED = "SUBMITTED"
DOING_STATUS_APPROVED = "APPROVED"
DOING_STATUS_REJECTED = "REJECTED"

SERIES_STATUS_ACTIVE = "ACTIVE"
SERIES_STATUS_AT_RISK = "AT_RISK"
SERIES_STATUS_CLOSED = "CLOSED"

SOURCE_SYSTEM = "SYSTEM"
SOURCE_USER = "USER"

REWARD_FIXED = "FIXED"
REWARD_COEF = "COEF"

EVENT_TASK_REWARD = "TASK_REWARD"
EVENT_PAYMENT = "PAYMENT"
EVENT_SERIES_BONUS = "SERIES_BONUS"
EVENT_MATH_BANK = "MATH_BANK"
EVENT_SESSION_RESET = "SESSION_RESET"
EVENT_SERIES_BONUS_REVERT = "SERIES_BONUS_REVERT"

STATE_ROLE_SELECT = "ROLE_SELECT"
STATE_PROJECT_SELECT = "PROJECT_SELECT"
STATE_PROJECT_PASSWORD = "PROJECT_PASSWORD"
STATE_OFFER_TITLE = "OFFER_TITLE"
STATE_OFFER_REWARD = "OFFER_REWARD"
STATE_INPUT_SCORE = "INPUT_SCORE"
STATE_ADMIN_ADD_TITLE = "ADMIN_ADD_TITLE"
STATE_ADMIN_ADD_REWARD = "ADMIN_ADD_REWARD"
STATE_ADMIN_PAY_AMOUNT = "ADMIN_PAY_AMOUNT"
STATE_ADMIN_END_SERIES_CONFIRM = "ADMIN_END_SERIES_CONFIRM"
STATE_PROJECT_CREATE_NAME = "PROJECT_CREATE_NAME"
STATE_PROJECT_CREATE_ADMINS = "PROJECT_CREATE_ADMINS"
STATE_PROJECT_CREATE_USERS = "PROJECT_CREATE_USERS"
STATE_PROJECT_CREATE_PASS = "PROJECT_CREATE_PASS"
STATE_PROJECT_EDIT_PASSWORD = "PROJECT_EDIT_PASSWORD"
STATE_PROJECT_EDIT_NAME = "PROJECT_EDIT_NAME"
STATE_PROJECT_EDIT_ADMINS = "PROJECT_EDIT_ADMINS"
STATE_PROJECT_EDIT_USERS = "PROJECT_EDIT_USERS"

USERS_HEADERS = [
    "username",
    "series",
    "bank_counter",
    "last_date",
    "role",
    "session_start",
]
PROJECTS_HEADERS = [
    "id",
    "name",
    "pass",
    "author",
    "admin",
    "user",
    "date_create",
]
TASKS_HEADERS = [
    "project",
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
    "project",
    "id",
    "task",
    "title",
    "description",
    "source",
    "reward_type",
    "reward_value",
    "executor",
    "date_create",
    "admin",
    "status",
    "status_date",
]
SERIES_HEADERS = [
    "project",
    "username",
    "start_date",
    "end_date",
    "status",
    "broken",
    "milestone_5_paid",
    "milestone_9_paid",
    "closed_by",
    "date_closed",
]
LEDGER_HEADERS = [
    "project",
    "timestamp",
    "username",
    "amount",
    "event_type",
    "comment",
]

SHEETS_SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

SYSTEM_TASK_SEED = [
    {"level": "1", "title": "Посуда", "description": "", "source": SOURCE_SYSTEM, "reward_type": REWARD_FIXED, "reward_value": 1.5},
    {"level": "1", "title": "Лоток", "description": "", "source": SOURCE_SYSTEM, "reward_type": REWARD_FIXED, "reward_value": 1.5},
    {"level": "1", "title": "Мусор", "description": "", "source": SOURCE_SYSTEM, "reward_type": REWARD_FIXED, "reward_value": 1.5},
    {"level": "1", "title": "Стол", "description": "", "source": SOURCE_SYSTEM, "reward_type": REWARD_FIXED, "reward_value": 1.5},
    {"level": "1", "title": "Убрать часть комнаты", "description": "", "source": SOURCE_SYSTEM, "reward_type": REWARD_FIXED, "reward_value": 1.5},
    {"level": "1", "title": "Магазин не ночью", "description": "", "source": SOURCE_SYSTEM, "reward_type": REWARD_FIXED, "reward_value": 1.5},
    {"level": "1+", "title": "Не опоздать в школу", "description": "", "source": SOURCE_SYSTEM, "reward_type": REWARD_FIXED, "reward_value": 2.5},
    {"level": "1++", "title": "Разбор темы по русскому", "description": "", "source": SOURCE_SYSTEM, "reward_type": REWARD_FIXED, "reward_value": 30.0},
    {"level": "2", "title": "Русский", "description": "Введите баллы ЦТ", "source": SOURCE_SYSTEM, "reward_type": REWARD_COEF, "reward_value": 0.5},
    {"level": "3", "title": "Английский", "description": "Введите баллы ЦТ", "source": SOURCE_SYSTEM, "reward_type": REWARD_COEF, "reward_value": 0.4},
    {"level": "4", "title": "Математика", "description": "Введите баллы ЦТ", "source": SOURCE_SYSTEM, "reward_type": REWARD_FIXED, "reward_value": 0.0},
]

HELP_TEXT = (
    "Каждый день выполняй минимум одно дело.\n\n"
    "Можешь предлагать задания.\n\n"
    "Пропуск дня сбрасывает серию.\n\n"
    "Задания могут быть с фиксированной оплатой (и ты такие можешь предлагать), а могут быть - с коэффициентом - их Администратор заводит)\n\n"
    "Майлстоуны: 5 дней (+10р), 9 дней (+25р).\n\n"
    "Полная серия - 14 дней. Делай хоть что-то каждый день - иначе ВСЮ серию начинаем сначала (накопленные деньги теряешь).\n\n"
    "Без форс-мажоров выплата в конце серии (частичные выплаты - по договоренности)"
))


INTRO_TEXT = (
    "Привет! Это бот для работы с заданиями, оплатами и сериями по проектам.\n\n"
    "Что дальше:\n"
    "• выбери роль — Администратор или Пользователь;\n"
    "• затем выбери проект;\n"
    "• если ты новый Администратор и проектов у тебя ещё нет, можно будет создать проект.\n\n"
    "Если что-то не открывается или ты не видишь свой проект, значит тебя ещё не добавили в него."
)
MAIN_MENU_REPLY_KB = ReplyKeyboardMarkup(
    [[KeyboardButton("🏠 Главное меню"), KeyboardButton("Re/start")]],
    resize_keyboard=True,
    is_persistent=True,
)


# ================= GOOGLE SHEETS INIT =================
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
            f"Лист '{title}' имеет неверные заголовки. Ожидается: {headers}. Сейчас: {header_row}"
        )
    return ws


def init_sheets():
    global users_ws, projects_ws, tasks_ws, doings_ws, series_ws, ledger_ws
    spreadsheet = gc.open(GOOGLE_SHEET_NAME)
    users_ws = get_or_create_worksheet(spreadsheet, "users", USERS_HEADERS)
    time.sleep(1.2)
    projects_ws = get_or_create_worksheet(spreadsheet, "projects", PROJECTS_HEADERS)
    time.sleep(1.2)
    tasks_ws = get_or_create_worksheet(spreadsheet, "tasks", TASKS_HEADERS)
    time.sleep(1.2)
    doings_ws = get_or_create_worksheet(spreadsheet, "doings", DOINGS_HEADERS)
    time.sleep(1.2)
    series_ws = get_or_create_worksheet(spreadsheet, "series", SERIES_HEADERS)
    time.sleep(1.2)
    ledger_ws = get_or_create_worksheet(spreadsheet, "ledger", LEDGER_HEADERS)


init_sheets()


# ================= IN-MEMORY STORAGE =================
users = {}
projects = {}
tasks = {}
doings = {}
series_records = []
ledger = []
project_task_counters = defaultdict(int)
project_doing_counters = defaultdict(int)
user_states = {}


# ================= UTIL =================
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


def parse_bool(value):
    return str(value).strip().upper() == "TRUE"


def bool_to_sheet(value):
    return "TRUE" if value else "FALSE"


def normalize_username(value):
    if not value:
        return ""
    value = value.strip()
    if value.startswith("@"):
        value = value[1:]
    return value


def split_users(raw):
    if not raw:
        return []
    parts = [normalize_username(item.strip()) for item in str(raw).split("|")]
    return [item for item in parts if item]


def join_users(items):
    normalized = [normalize_username(item) for item in items if normalize_username(item)]
    return "|".join(normalized)


def get_ctx(context, key, default=None):
    return context.user_data.get(key, default)


def set_ctx(context, key, value):
    context.user_data[key] = value


def clear_temp_flow(username, context):
    user_states.pop(username, None)
    for key in [
        "selected_task_id",
        "offer_title",
        "admin_task_title",
        "payment_project",
        "payment_target",
        "project_candidates",
        "selected_project_id",
        "selected_role",
        "project_create_name",
        "project_create_admins",
        "project_create_users",
        "project_edit_action",
        "project_edit_target_id",
        "pending_risk_doing_id",
    ]:
        context.user_data.pop(key, None)


def set_current_role_project(context, role, project_id):
    context.user_data["current_role"] = role
    context.user_data["current_project_id"] = project_id


def get_current_project_id(context):
    return context.user_data.get("current_project_id")


def get_current_role(context):
    return context.user_data.get("current_role")


def get_project_name(project_id):
    project = projects.get(project_id)
    return project.get("name", project_id) if project else project_id


def get_balance(username, project_id=None):
    total = 0.0
    for event in ledger:
        if event.get("username") != username:
            continue
        if project_id and event.get("project") != project_id:
            continue
        total += parse_float_safe(event.get("amount", 0))
    return total


def next_task_id(project_id):
    project_task_counters[project_id] += 1
    return str(project_task_counters[project_id])


def next_doing_id(project_id):
    project_doing_counters[project_id] += 1
    return str(project_doing_counters[project_id])


def get_project_admins(project_id):
    project = projects.get(project_id, {})
    return split_users(project.get("admin", ""))


def get_project_users(project_id):
    project = projects.get(project_id, {})
    return split_users(project.get("user", ""))


def user_has_project_role(username, project_id, role):
    username = normalize_username(username)
    if role == ROLE_ADMIN:
        return username in get_project_admins(project_id)
    return username in get_project_users(project_id)


def get_accessible_projects(username, role):
    result = []
    for project_id, project in projects.items():
        if user_has_project_role(username, project_id, role):
            result.append(project)
    result.sort(key=lambda item: (item.get("name", ""), item.get("id", "")))
    return result


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


# ================= SAVE HELPERS =================
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


def save_project(project_id):
    project = projects[project_id]
    row = [
        project["id"],
        project.get("name", ""),
        project.get("pass", ""),
        project.get("author", ""),
        project.get("admin", ""),
        project.get("user", ""),
        project.get("date_create", ""),
    ]

    def _write(pid=project_id, data=row):
        try:
            cell = projects_ws.find(str(pid))
            projects_ws.update(f"A{cell.row}:G{cell.row}", [data])
        except Exception:
            safe_append(projects_ws, data)

    enqueue(_write)


def task_key(project_id, task_id):
    return f"{project_id}:{task_id}"


def doing_key(project_id, doing_id):
    return f"{project_id}:{doing_id}"


def save_task(key):
    task = tasks[key]
    row = [
        task.get("project", ""),
        task.get("id", ""),
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

    def _write(data=row):
        all_rows = tasks_ws.get_all_records()
        target_row = None
        for index, item in enumerate(all_rows, start=2):
            if str(item.get("project", "")) == str(task.get("project", "")) and str(item.get("id", "")) == str(task.get("id", "")):
                target_row = index
                break
        if target_row:
            tasks_ws.update(f"A{target_row}:K{target_row}", [data])
        else:
            safe_append(tasks_ws, data)

    enqueue(_write)


def save_doing(key):
    doing = doings[key]
    row = [
        doing.get("project", ""),
        doing.get("id", ""),
        doing.get("task", ""),
        doing.get("title", ""),
        doing.get("description", ""),
        doing.get("source", ""),
        doing.get("reward_type", ""),
        doing.get("reward_value", 0),
        doing.get("executor", ""),
        doing.get("date_create", ""),
        doing.get("admin", ""),
        doing.get("status", ""),
        doing.get("status_date", ""),
    ]

    def _write(data=row):
        all_rows = doings_ws.get_all_records()
        target_row = None
        for index, item in enumerate(all_rows, start=2):
            if str(item.get("project", "")) == str(doing.get("project", "")) and str(item.get("id", "")) == str(doing.get("id", "")):
                target_row = index
                break
        if target_row:
            doings_ws.update(f"A{target_row}:M{target_row}", [data])
        else:
            safe_append(doings_ws, data)

    enqueue(_write)


def series_identity(record):
    return (
        record.get("project", ""),
        record.get("username", ""),
        record.get("start_date", ""),
    )


def save_series(record):
    row = [
        record.get("project", ""),
        record.get("username", ""),
        record.get("start_date", ""),
        record.get("end_date", ""),
        record.get("status", ""),
        bool_to_sheet(record.get("broken", False)),
        bool_to_sheet(record.get("milestone_5_paid", False)),
        bool_to_sheet(record.get("milestone_9_paid", False)),
        record.get("closed_by", ""),
        record.get("date_closed", ""),
    ]

    identity = series_identity(record)

    def _write(data=row, ident=identity):
        all_rows = series_ws.get_all_records()
        target_row = None
        for index, item in enumerate(all_rows, start=2):
            row_ident = (
                str(item.get("project", "")),
                str(item.get("username", "")),
                str(item.get("start_date", "")),
            )
            if row_ident == ident:
                target_row = index
                break
        if target_row:
            series_ws.update(f"A{target_row}:J{target_row}", [data])
        else:
            safe_append(series_ws, data)

    enqueue(_write)


def log_event(project_id, username, event_type, amount=0.0, comment=""):
    row = [project_id, now_str(), username, amount, event_type, comment]

    def _write(data=row):
        safe_append(ledger_ws, data)

    enqueue(_write)
    ledger.append(
        {
            "project": project_id,
            "timestamp": row[1],
            "username": username,
            "amount": amount,
            "event_type": event_type,
            "comment": comment,
        }
    )


# ================= LOAD DATA =================
def load_data():
    time.sleep(1.2)
    for row in users_ws.get_all_records():
        username = normalize_username(row.get("username", ""))
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
    for row in projects_ws.get_all_records():
        project_id = str(row.get("id", "")).strip()
        if not project_id:
            continue
        projects[project_id] = {
            "id": project_id,
            "name": row.get("name", ""),
            "pass": str(row.get("pass", "")),
            "author": normalize_username(row.get("author", "")),
            "admin": join_users(split_users(row.get("admin", ""))),
            "user": join_users(split_users(row.get("user", ""))),
            "date_create": str(row.get("date_create", "")),
        }

    time.sleep(1.2)
    for row in tasks_ws.get_all_records():
        project_id = str(row.get("project", "")).strip()
        task_id = str(row.get("id", "")).strip()
        if not project_id or not task_id:
            continue
        key = task_key(project_id, task_id)
        tasks[key] = {
            "project": project_id,
            "id": task_id,
            "title": row.get("title", ""),
            "description": row.get("description", ""),
            "source": row.get("source", ""),
            "reward_type": row.get("reward_type", ""),
            "reward_value": parse_float_safe(row.get("reward_value", 0)),
            "status": row.get("status", ""),
            "author": normalize_username(row.get("author", "")),
            "date": str(row.get("date", "")),
        }
        if task_id.isdigit():
            project_task_counters[project_id] = max(project_task_counters[project_id], int(task_id))

    time.sleep(1.2)
    for row in doings_ws.get_all_records():
        project_id = str(row.get("project", "")).strip()
        doing_id = str(row.get("id", "")).strip()
        if not project_id or not doing_id:
            continue
        key = doing_key(project_id, doing_id)
        doings[key] = {
            "project": project_id,
            "id": doing_id,
            "task": str(row.get("task", "")),
            "title": row.get("title", ""),
            "description": row.get("description", ""),
            "source": row.get("source", ""),
            "reward_type": row.get("reward_type", ""),
            "reward_value": parse_float_safe(row.get("reward_value", 0)),
            "executor": normalize_username(row.get("executor", "")),
            "date_create": str(row.get("date_create", "")),
            "admin": normalize_username(row.get("admin", "")),
            "status": row.get("status", ""),
            "status_date": str(row.get("status_date", "")),
        }
        if doing_id.isdigit():
            project_doing_counters[project_id] = max(project_doing_counters[project_id], int(doing_id))

    time.sleep(1.2)
    for row in series_ws.get_all_records():
        project_id = str(row.get("project", "")).strip()
        username = normalize_username(row.get("username", ""))
        if not project_id or not username:
            continue
        series_records.append(
            {
                "project": project_id,
                "username": username,
                "start_date": str(row.get("start_date", "")),
                "end_date": str(row.get("end_date", "")),
                "status": row.get("status", ""),
                "broken": parse_bool(row.get("broken", "FALSE")),
                "milestone_5_paid": parse_bool(row.get("milestone_5_paid", "FALSE")),
                "milestone_9_paid": parse_bool(row.get("milestone_9_paid", "FALSE")),
                "closed_by": normalize_username(row.get("closed_by", "")),
                "date_closed": str(row.get("date_closed", "")),
            }
        )

    time.sleep(1.2)
    ledger.extend(ledger_ws.get_all_records())


load_data()


# ================= BUSINESS LOGIC =================



def calculate_reward(task, score=None):
    reward_type = task.get("rewardtype")
    reward_value = parse_float_safe(task.get("rewardvalue", 0))
    if reward_type == REWARD_COEF:
        if score is None:
            raise ValueError("Введите значение для задачи с коэффициентом.")
        return float(score) * reward_value
    return reward_value


def create_doing_from_task(project_id, task_id, executor, score=None):
    key = task_key(project_id, task_id)
    if key not in tasks:
        raise ValueError("Задание не найдено")

    task = tasks[key]
    reward = calculate_reward(task, score=score)
    doing_id = next_doing_id(project_id)
    d_key = doing_key(project_id, doing_id)
    doings[d_key] = {
        "project": project_id,
        "id": doing_id,
        "task": task_id,
        "title": task.get("title", ""),
        "description": task.get("description", ""),
        "source": task.get("source", ""),
        "reward_type": task.get("reward_type", ""),
        "reward_value": reward,
        "executor": executor,
        "date_create": str(today()),
        "admin": "",
        "status": DOING_STATUS_SUBMITTED,
        "status_date": str(today()),
    }
    save_doing(d_key)
    return doings[d_key]


def get_active_series(project_id, username):
    active = []
    for item in series_records:
        if item.get("project") == project_id and item.get("username") == username and item.get("status") in {SERIES_STATUS_ACTIVE, SERIES_STATUS_AT_RISK}:
            active.append(item)
    if not active:
        return None
    active.sort(key=lambda x: x.get("start_date", ""), reverse=True)
    return active[0]


def create_series_if_needed(project_id, username):
    current = get_active_series(project_id, username)
    if current:
        return current
    new_record = {
        "project": project_id,
        "username": username,
        "start_date": str(today()),
        "end_date": "",
        "status": SERIES_STATUS_ACTIVE,
        "broken": False,
        "milestone_5_paid": False,
        "milestone_9_paid": False,
        "closed_by": "",
        "date_closed": "",
    }
    series_records.append(new_record)
    save_series(new_record)
    return new_record


def update_series_after_approval(project_id, username):
    record = create_series_if_needed(project_id, username)
    start_date = parse_date_safe(record.get("start_date")) or today()
    current_day = (today() - start_date).days + 1

    if current_day >= 5 and not record.get("milestone_5_paid"):
        record["milestone_5_paid"] = True
        log_event(project_id, username, EVENT_SERIES_BONUS, 10, "Майлстоун серии: 5 дней")

    if current_day >= 9 and not record.get("milestone_9_paid"):
        record["milestone_9_paid"] = True
        log_event(project_id, username, EVENT_SERIES_BONUS, 25, "Майлстоун серии: 9 дней")

    save_series(record)
    return record


def detect_series_risk(project_id, username):
    record = get_active_series(project_id, username)
    if not record:
        return None
    if record.get("status") == SERIES_STATUS_AT_RISK:
        return record

    start_date = parse_date_safe(record.get("start_date"))
    if not start_date:
        return None

    approved_dates = []
    for doing in doings.values():
        if doing.get("project") != project_id:
            continue
        if doing.get("executor") != username:
            continue
        if doing.get("status") != DOING_STATUS_APPROVED:
            continue
        approved_date = parse_date_safe(doing.get("status_date") or doing.get("date_create"))
        if approved_date:
            approved_dates.append(approved_date)

    if not approved_dates:
        return None

    last_approved_date = max(approved_dates)
    if (today() - last_approved_date).days > 1:
        record["status"] = SERIES_STATUS_AT_RISK
        record["broken"] = True
        save_series(record)
        return record
    return None


def close_series(project_id, username, closed_by):
    record = get_active_series(project_id, username)
    if not record:
        return False, "Активной серии нет."

    if record.get("milestone_5_paid"):
        log_event(project_id, username, EVENT_SERIES_BONUS_REVERT, -10, "Отмена майлстоуна 5 дней при закрытии серии")
    if record.get("milestone_9_paid"):
        log_event(project_id, username, EVENT_SERIES_BONUS_REVERT, -25, "Отмена майлстоуна 9 дней при закрытии серии")

    record["status"] = SERIES_STATUS_CLOSED
    record["end_date"] = str(today())
    record["closed_by"] = closed_by
    record["date_closed"] = str(today())
    save_series(record)
    return True, "Серия закрыта."




def build_stats_text(project_id, username):
    ensure_user(username)
    user = users.get(username, {})
    current_series = get_active_series(project_id, username)
    series_text = "Нет активной серии"
    if current_series:
        series_text = (
            f"{current_series.get('status', '—')} с {current_series.get('start_date', '—')}"
        )

    approved = []
    pending = []
    rejected = []
    for doing in doings.values():
        if doing.get("project") != project_id or doing.get("executor") != username:
            continue
        if doing.get("status") == DOING_STATUS_APPROVED:
            approved.append(doing)
        elif doing.get("status") == DOING_STATUS_SUBMITTED:
            pending.append(doing)
        elif doing.get("status") == DOING_STATUS_REJECTED:
            rejected.append(doing)

    approved.sort(key=lambda x: (x.get("status_date", ""), x.get("id", "")))
    pending.sort(key=lambda x: (x.get("date_create", ""), x.get("id", "")))
    rejected.sort(key=lambda x: (x.get("status_date", ""), x.get("id", "")))

    project_events = [item for item in ledger if item.get("project") == project_id and item.get("username") == username]
    payouts = [item for item in project_events if str(item.get("event_type", "")).upper() == EVENT_PAYMENT]
    balance = sum(parse_float_safe(item.get("amount", 0)) for item in project_events)

    lines = [f"📊 Статистика @{username} / {get_project_name(project_id)}"]
    lines.append(f"🔁 Серия: {series_text}")
    lines.append(f"💼 Баланс проекта: {balance:.1f} р.")
    lines.append(f"📐 Банк математики: {user.get('bank_counter', 0)}")
    lines.append("")

    lines.append("✅ Одобренные задания:")
    if approved:
        for item in approved:
            lines.append(f"  • {item.get('status_date', '')} — {item.get('title', '—')} — +{parse_float_safe(item.get('reward_value', 0)):.1f} р.")
    else:
        lines.append("  Нет")
    lines.append("")

    lines.append("🕓 Выполненные ещё неодобренные задания:")
    if pending:
        for item in pending:
            lines.append(f"  • {item.get('date_create', '')} — {item.get('title', '—')} — +{parse_float_safe(item.get('reward_value', 0)):.1f} р.")
    else:
        lines.append("  Нет")
    lines.append("")

    lines.append("❌ Выполненные отклонённые задания:")
    if rejected:
        for item in rejected:
            lines.append(f"  • {item.get('status_date', '')} — {item.get('title', '—')} — +{parse_float_safe(item.get('reward_value', 0)):.1f} р.")
    else:
        lines.append("  Нет")
    lines.append("")

    lines.append("💸 Выплаты:")
    if payouts:
        for item in payouts:
            lines.append(f"  • {str(item.get('timestamp', ''))[:10]} — {parse_float_safe(item.get('amount', 0)):.1f} р.")
    else:
        lines.append("  Нет")

    return "\n".join(lines)


# ================= UI HELPERS =================
def role_selection_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Администратор", callback_data="role_admin")],
            [InlineKeyboardButton("Пользователь", callback_data="role_user")],
        ]
    )


def project_selection_keyboard(project_list, role):
    buttons = []
    for project in project_list:
        buttons.append([
            InlineKeyboardButton(
                project.get("name", project.get("id", "Проект")),
                callback_data=f"project_pick_{role}_{project['id']}",
            )
        ])
    buttons.append([InlineKeyboardButton("← К выбору роли", callback_data="restart_role")])
    return InlineKeyboardMarkup(buttons)


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
            [InlineKeyboardButton("Прервать серию", callback_data="admin_end_series")],
            [InlineKeyboardButton("Новый проект", callback_data="admin_new_project")],
            [InlineKeyboardButton("Редактировать текущий проект", callback_data="admin_edit_project")],
            [InlineKeyboardButton("В главное меню", callback_data="main_menu")],
        ]
    )


def back_main_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("В главное меню", callback_data="main_menu")]])


async def send_or_edit(update: Update, text: str, reply_markup=None):
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)


async def send_restart_screen(update: Update):
    separator = "\n".join([
        "━━━━━━━━━━━━━━━━━━━━",
        "🔄 Перезапуск диалога",
        "Выбери роль заново",
        "━━━━━━━━━━━━━━━━━━━━",
    ])
    if update.callback_query:
        await update.callback_query.message.reply_text(separator, reply_markup=MAIN_MENU_REPLY_KB)
    else:
        await update.message.reply_text(separator, reply_markup=MAIN_MENU_REPLY_KB)


# ================= VIEWS =================
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role = get_current_role(context)
    project_id = get_current_project_id(context)
    if not role or not project_id:
        await send_or_edit(update, "Сначала выбери роль и проект.", reply_markup=back_main_keyboard())
        return

    project_name = get_project_name(project_id)
    if role == ROLE_ADMIN:
        text = f"Меню Администратора\nПроект: {project_name}"
        markup = admin_menu_keyboard()
    else:
        text = f"Меню Пользователя\nПроект: {project_name}"
        markup = user_menu_keyboard()
    await send_or_edit(update, text, reply_markup=markup)


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_or_edit(update, HELP_TEXT, reply_markup=back_main_keyboard())


# ================= START FLOW =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = normalize_username(update.effective_user.username)
    if not username:
        await update.message.reply_text("У тебя не задан username в Telegram.")
        return

    ensure_user(username)
    clear_temp_flow(username, context)
    await send_restart_screen(update)
    user_states[username] = STATE_ROLE_SELECT
    if update.callback_query:
        await update.callback_query.message.reply_text("Выбери роль:", reply_markup=role_selection_keyboard())
    else:
        await update.message.reply_text("Выбери роль:", reply_markup=role_selection_keyboard())


async def show_role_projects(update: Update, context: ContextTypes.DEFAULT_TYPE, role: str):
    username = normalize_username(update.effective_user.username)
    candidates = get_accessible_projects(username, role)
    set_ctx(context, "selected_role", role)

    if not candidates:
        await send_or_edit(update, "Нет доступных проектов для этой роли.", reply_markup=back_main_keyboard())
        return

    set_ctx(context, "project_candidates", [item["id"] for item in candidates])
    user_states[username] = STATE_PROJECT_SELECT
    role_name = "Администратор" if role == ROLE_ADMIN else "Пользователь"
    await send_or_edit(
        update,
        f"Роль: {role_name}\nВыбери проект:",
        reply_markup=project_selection_keyboard(candidates, role),
    )


# ================= USER FLOWS =================

async def show_available_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project_id = get_current_project_id(context)
    available_tasks = [task for task in tasks.values() if task.get("project") == project_id and task.get("status") == STATUS_AVAILABLE]
    if not available_tasks:
        await send_or_edit(update, "Нет доступных заданий.", reply_markup=back_main_keyboard())
        return
    available_tasks.sort(key=lambda item: int(item.get("id", 0)))
    buttons = []
    for task in available_tasks:
        reward_value = parse_float_safe(task.get("rewardvalue", 0))
        if task.get("rewardtype") == REWARD_COEF:
            reward_label = f"коэффициент {reward_value:g}"
        else:
            reward_label = f"{reward_value:.2f} р."
        label = f"{task.get('id')}. {task.get('title')} — {reward_label}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"taskselect|{task.get('id')}")])
    buttons.append([InlineKeyboardButton("Назад", callback_data="mainmenu")])
    await send_or_edit(update, "Выберите задание:", reply_markup=InlineKeyboardMarkup(buttons))

async def handle_task_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, task_id: str):
    username = normalize_username(update.effective_user.username)
    project_id = get_current_project_id(context)
    key = task_key(project_id, task_id)
    task = tasks.get(key)
    if not task or task.get("status") != STATUS_AVAILABLE:
        await update.callback_query.answer("Задание недоступно")
        return

    if task.get("level") in {"2", "3", "4"}:
        user_states[username] = STATE_INPUT_SCORE
        set_ctx(context, "selected_task_id", task_id)
        await update.callback_query.message.reply_text(f"Введи баллы для задания «{task.get('title', '')}»:")
        return

    doing = create_doing_from_task(project_id, task_id, username)
    risk = detect_series_risk(project_id, username)
    text = f"Задание отправлено на проверку: {doing['title']} — {doing['reward_value']:.1f} р."
    if risk:
        text += "\n\n⚠️ У тебя Серия под угрозой срыва, обратись к Администратору."
    await update.callback_query.message.reply_text(text)


async def show_user_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = normalize_username(update.effective_user.username)
    project_id = get_current_project_id(context)
    text = build_stats_text(project_id, username)
    await send_or_edit(update, text[:4096], reply_markup=back_main_keyboard())


# ================= ADMIN FLOWS =================
async def show_admin_pending_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project_id = get_current_project_id(context)
    pending = [item for item in doings.values() if item.get("project") == project_id and item.get("status") == DOING_STATUS_SUBMITTED]
    if not pending:
        await send_or_edit(update, "Нет непроверенных заданий.", reply_markup=admin_menu_keyboard())
        return

    executors = sorted({item.get("executor") for item in pending if item.get("executor")})
    lines = ["Выбери пользователя для проверки:"]
    buttons = []
    for executor in executors:
        count = sum(1 for item in pending if item.get("executor") == executor)
        lines.append(f"@{executor}: {count} шт.")
        buttons.append([InlineKeyboardButton(f"@{executor}", callback_data=f"admin_pending_user_{executor}")])
    buttons.append([InlineKeyboardButton("В главное меню", callback_data="main_menu")])
    await send_or_edit(update, "\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))


async def show_admin_pending_for_user(update: Update, context: ContextTypes.DEFAULT_TYPE, target: str):
    project_id = get_current_project_id(context)
    target_doings = [
        item for item in doings.values()
        if item.get("project") == project_id and item.get("executor") == target and item.get("status") == DOING_STATUS_SUBMITTED
    ]
    if not target_doings:
        await send_or_edit(update, f"У @{target} нет непроверенных заданий.", reply_markup=admin_menu_keyboard())
        return

    target_doings.sort(key=lambda item: int(item.get("id", 0)))
    lines = [f"@{target} — непроверенные задания:", ""]
    buttons = []
    for index, item in enumerate(target_doings, start=1):
        lines.append(f"{index}. {item.get('date_create', '')} / {item.get('title', '—')} — {parse_float_safe(item.get('reward_value', 0)):.1f} р.")
        buttons.append([InlineKeyboardButton(str(index), callback_data=f"admin_doing_action_{item['id']}")])

    buttons.append([InlineKeyboardButton("← Назад", callback_data="admin_pending")])
    buttons.append([InlineKeyboardButton("В главное меню", callback_data="main_menu")])
    await send_or_edit(update, "\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))


async def show_admin_doing_action(update: Update, context: ContextTypes.DEFAULT_TYPE, doing_id: str):
    project_id = get_current_project_id(context)
    key = doing_key(project_id, doing_id)
    doing = doings.get(key)
    if not doing:
        await update.callback_query.answer("Выполнение не найдено")
        return

    target = doing.get("executor")
    risk = detect_series_risk(project_id, target)
    warning = ""
    extra_buttons = []
    if risk:
        warning = "\n\n⚠️ Пользователь пропустил день! Решай этот вопрос или прерывай Серию."
        extra_buttons.append([
            InlineKeyboardButton("Отработано", callback_data=f"series_fix_{doing_id}"),
            InlineKeyboardButton("Напомнить завтра", callback_data=f"series_remind_{doing_id}"),
        ])

    text = (
        f"Задание: {doing.get('title', '—')}\n"
        f"Исполнитель: @{doing.get('executor', '?')}\n"
        f"Дата: {doing.get('date_create', '')}\n"
        f"Стоимость: {parse_float_safe(doing.get('reward_value', 0)):.1f} р.\n\n"
        f"Принять или отклонить?{warning}"
    )
    buttons = [
        [
            InlineKeyboardButton("✅ Принять", callback_data=f"admin_approve_doing_{doing_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"admin_reject_doing_{doing_id}"),
        ],
    ]
    buttons.extend(extra_buttons)
    buttons.append([
        InlineKeyboardButton("← Назад", callback_data=f"admin_pending_user_{doing.get('executor', '')}"),
        InlineKeyboardButton("В главное меню", callback_data="main_menu"),
    ])
    await send_or_edit(update, text, reply_markup=InlineKeyboardMarkup(buttons))


async def approve_doing(update: Update, context: ContextTypes.DEFAULT_TYPE, doing_id: str):
    project_id = get_current_project_id(context)
    admin_username = normalize_username(update.effective_user.username)
    key = doing_key(project_id, doing_id)
    doing = doings.get(key)
    if not doing or doing.get("status") != DOING_STATUS_SUBMITTED:
        await update.callback_query.answer("Это выполнение уже обработано или не найдено")
        return

    username = doing.get("executor")
    doing["status"] = DOING_STATUS_APPROVED
    doing["status_date"] = str(today())
    doing["admin"] = admin_username
    save_doing(key)

    reward = parse_float_safe(doing.get("reward_value", 0))
    log_event(project_id, username, EVENT_TASK_REWARD, reward, f"Одобрено: {doing.get('title', '')}")
    create_series_if_needed(project_id, username)
    update_series_after_approval(project_id, username)

    ensure_user(username)
    users[username]["last_date"] = today()
    save_user(username)

    await update.callback_query.answer("Задание одобрено")
    await show_admin_pending_users(update, context)


async def reject_doing(update: Update, context: ContextTypes.DEFAULT_TYPE, doing_id: str):
    project_id = get_current_project_id(context)
    admin_username = normalize_username(update.effective_user.username)
    key = doing_key(project_id, doing_id)
    doing = doings.get(key)
    if not doing or doing.get("status") != DOING_STATUS_SUBMITTED:
        await update.callback_query.answer("Это выполнение уже обработано или не найдено")
        return

    doing["status"] = DOING_STATUS_REJECTED
    doing["status_date"] = str(today())
    doing["admin"] = admin_username
    save_doing(key)
    await update.callback_query.answer("Задание отклонено")
    await show_admin_pending_users(update, context)


async def mark_series_fixed(update: Update, context: ContextTypes.DEFAULT_TYPE, doing_id: str):
    project_id = get_current_project_id(context)
    key = doing_key(project_id, doing_id)
    doing = doings.get(key)
    if not doing:
        await update.callback_query.answer("Выполнение не найдено")
        return
    record = get_active_series(project_id, doing.get("executor"))
    if record:
        record["status"] = SERIES_STATUS_ACTIVE
        record["broken"] = False
        save_series(record)
    await update.callback_query.answer("Серия переведена обратно в ACTIVE")
    await show_admin_doing_action(update, context, doing_id)


async def remind_series_tomorrow(update: Update, context: ContextTypes.DEFAULT_TYPE, doing_id: str):
    await update.callback_query.answer("Напоминание оставлено")
    await show_admin_doing_action(update, context, doing_id)


async def show_admin_offers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project_id = get_current_project_id(context)
    offers = [task for task in tasks.values() if task.get("project") == project_id and task.get("status") == STATUS_OFFERED]
    if not offers:
        await send_or_edit(update, "Нет предложенных заданий.", reply_markup=admin_menu_keyboard())
        return

    offers.sort(key=lambda item: int(item.get("id", 0)))
    lines = ["Предложенные задания:"]
    buttons = []
    for item in offers:
        lines.append(f"{item['id']}. {item.get('title', '—')} — {parse_float_safe(item.get('reward_value', 0)):.1f} р.")
        buttons.append([
            InlineKeyboardButton(f"Одобрить {item['id']}", callback_data=f"admin_approve_offer_{item['id']}"),
            InlineKeyboardButton(f"Отклонить {item['id']}", callback_data=f"admin_reject_offer_{item['id']}"),
        ])
    buttons.append([InlineKeyboardButton("В главное меню", callback_data="main_menu")])
    await send_or_edit(update, "\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))


async def show_admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project_id = get_current_project_id(context)
    usernames = sorted({doing.get("executor") for doing in doings.values() if doing.get("project") == project_id and doing.get("executor")})
    usernames.extend([item for item in get_project_users(project_id) if item not in usernames])
    if not usernames:
        await send_or_edit(update, "Нет пользователей для просмотра статистики.", reply_markup=admin_menu_keyboard())
        return

    buttons = [[InlineKeyboardButton(f"@{user}", callback_data=f"admin_stats_user_{user}")] for user in usernames]
    buttons.append([InlineKeyboardButton("В главное меню", callback_data="main_menu")])
    await send_or_edit(update, "Выбери пользователя:", reply_markup=InlineKeyboardMarkup(buttons))


async def show_admin_delete_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project_id = get_current_project_id(context)
    available_tasks = [task for task in tasks.values() if task.get("project") == project_id and task.get("status") == STATUS_AVAILABLE]
    if not available_tasks:
        await send_or_edit(update, "Нет доступных заданий для удаления.", reply_markup=admin_menu_keyboard())
        return

    available_tasks.sort(key=lambda item: int(item.get("id", 0)))
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
        buttons.append([InlineKeyboardButton(f"Удалить {item['id']}", callback_data=f"admin_archive_task_{item['id']}")])
    buttons.append([InlineKeyboardButton("В главное меню", callback_data="main_menu")])
    await send_or_edit(update, "\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))


async def show_project_edit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project_id = get_current_project_id(context)
    project = projects.get(project_id)
    if not project:
        await send_or_edit(update, "Проект не найден.", reply_markup=admin_menu_keyboard())
        return

    text = (
        f"Редактирование проекта: {project.get('name', project_id)}\n"
        f"Админы: {project.get('admin', '') or '—'}\n"
        f"Юзеры: {project.get('user', '') or '—'}\n\n"
        f"Выбери действие:"
    )
    buttons = [
        [InlineKeyboardButton("Изм. имя", callback_data="edit_project_name")],
        [InlineKeyboardButton("Изм. админов", callback_data="edit_project_admins")],
        [InlineKeyboardButton("Изм. юзеров", callback_data="edit_project_users")],
        [InlineKeyboardButton("В главное меню", callback_data="main_menu")],
    ]
    await send_or_edit(update, text, reply_markup=InlineKeyboardMarkup(buttons))


# ================= TEXT HANDLER =================
async def global_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = normalize_username(update.effective_user.username)
    text = (update.message.text or "").strip()
    ensure_user(username)

    if text == "🏠 Главное меню":
        await show_main_menu(update, context)
        return

    if text == "Re/start":
        clear_temp_flow(username, context)
        await start(update, context)
        return

    state = user_states.get(username)

    if state == STATE_PROJECT_PASSWORD:
        project_id = get_ctx(context, "selected_project_id")
        role = get_ctx(context, "selected_role")
        project = projects.get(project_id)
        if not project:
            await update.message.reply_text("Проект не найден. Нажми Re/start.")
            return
        if str(text) != str(project.get("pass", "")):
            await update.message.reply_text("Неверный пароль проекта. Попробуй ещё раз или нажми Re/start.")
            return
        users[username]["role"] = role
        save_user(username)
        user_states.pop(username, None)
        set_current_role_project(context, role, project_id)
        await update.message.reply_text(f"Вход выполнен. Проект: {project.get('name', project_id)}")
        await show_main_menu(update, context)
        return

    if state == STATE_OFFER_TITLE:
        set_ctx(context, "offer_title", text)
        user_states[username] = STATE_OFFER_REWARD
        await update.message.reply_text("Укажи награду за задание в рублях:")
        return

    if state == STATE_OFFER_REWARD:
        reward = parse_float_safe(text.replace(",", "."), default=None)
        if reward is None or reward < 0:
            await update.message.reply_text("Введите корректное неотрицательное число.")
            return
        project_id = get_current_project_id(context)
        task_id = next_task_id(project_id)
        key = task_key(project_id, task_id)
        tasks[key] = {
            "project": project_id,
            "id": task_id,
            "level": "USER",
            "title": get_ctx(context, "offer_title", "Без названия"),
            "description": "",
            "source": SOURCE_USER,
            "reward_type": REWARD_FIXED,
            "reward_value": reward,
            "status": STATUS_OFFERED,
            "author": username,
            "date": str(today()),
        }
        save_task(key)
        clear_temp_flow(username, context)
        set_current_role_project(context, ROLE_USER, project_id)
        await update.message.reply_text("Предложение задания отправлено администраторам проекта.")
        return

    if state == STATE_INPUT_SCORE:
        task_id = get_ctx(context, "selected_task_id")
        score = parse_float_safe(text, default=None)
        if score is None:
            await update.message.reply_text("Введите число.")
            return
        if score < 0:
            await update.message.reply_text("Баллы не могут быть отрицательными.")
            return
        project_id = get_current_project_id(context)
        try:
            doing = create_doing_from_task(project_id, task_id, username, score=score)
        except ValueError as exc:
            await update.message.reply_text(str(exc))
            return
        clear_temp_flow(username, context)
        set_current_role_project(context, ROLE_USER, project_id)
        risk = detect_series_risk(project_id, username)
        result = f"Задание отправлено на проверку: {doing['title']} — {doing['reward_value']:.1f} р."
        if risk:
            result += "\n\n⚠️ У тебя Серия под угрозой срыва, обратись к Администратору."
        await update.message.reply_text(result)
        return

    if state == STATE_ADMIN_ADD_TITLE:
        set_ctx(context, "admin_task_title", text)
        user_states[username] = STATE_ADMIN_ADD_REWARD
        await update.message.reply_text("Укажи награду в рублях:")
        return

    if state == STATE_ADMIN_ADD_REWARD:
        reward = parse_float_safe(text.replace(",", "."), default=None)
        if reward is None or reward < 0:
            await update.message.reply_text("Введите корректное неотрицательное число.")
            return
        project_id = get_current_project_id(context)
        task_id = next_task_id(project_id)
        key = task_key(project_id, task_id)
        tasks[key] = {
            "project": project_id,
            "id": task_id,
            "level": "USER",
            "title": get_ctx(context, "admin_task_title", "Без названия"),
            "description": "",
            "source": SOURCE_SYSTEM,
            "reward_type": REWARD_FIXED,
            "reward_value": reward,
            "status": STATUS_AVAILABLE,
            "author": username,
            "date": str(today()),
        }
        save_task(key)
        clear_temp_flow(username, context)
        set_current_role_project(context, ROLE_ADMIN, project_id)
        await update.message.reply_text("Новое задание добавлено.")
        return

    if state == STATE_ADMIN_PAY_AMOUNT:
        amount = parse_float_safe(text, default=None)
        if amount is None:
            await update.message.reply_text("Введите корректное число.")
            return
        target = get_ctx(context, "payment_target")
        project_id = get_ctx(context, "payment_project")
        log_event(project_id, target, EVENT_PAYMENT, amount, "Ручная выплата / долг")
        clear_temp_flow(username, context)
        set_current_role_project(context, ROLE_ADMIN, project_id)
        await update.message.reply_text(f"Запись в ledger добавлена: @{target} / {amount:.1f} р.")
        return

    if state == STATE_ADMIN_END_SERIES_CONFIRM:
        if text != "ДА":
            project_id = get_current_project_id(context)
            clear_temp_flow(username, context)
            set_current_role_project(context, ROLE_ADMIN, project_id)
            await update.message.reply_text("Закрытие серии отменено.")
            return
        target = get_ctx(context, "payment_target")
        project_id = get_current_project_id(context)
        ok, message = close_series(project_id, target, username)
        clear_temp_flow(username, context)
        set_current_role_project(context, ROLE_ADMIN, project_id)
        await update.message.reply_text(message)
        return

    if state == STATE_PROJECT_CREATE_NAME:
        set_ctx(context, "project_create_name", text)
        set_ctx(context, "project_create_admins", [username])
        user_states[username] = STATE_PROJECT_CREATE_ADMINS
        await update.message.reply_text("Вы будете назначены Администратором по умолчанию. Укажите ещё Администраторов через | (с @) или отправьте - :")
        return

    if state == STATE_PROJECT_CREATE_ADMINS:
        admins = get_ctx(context, "project_create_admins", [username])
        if text != "-":
            admins.extend(split_users(text.replace(",", "|")))
        set_ctx(context, "project_create_admins", sorted(set(admins)))
        user_states[username] = STATE_PROJECT_CREATE_USERS
        await update.message.reply_text("Укажите никнеймы пользователей через | (с @):")
        return

    if state == STATE_PROJECT_CREATE_USERS:
        users_list = split_users(text.replace(",", "|"))
        set_ctx(context, "project_create_users", users_list)
        user_states[username] = STATE_PROJECT_CREATE_PASS
        await update.message.reply_text("Укажите пароль проекта:")
        return

    if state == STATE_PROJECT_CREATE_PASS:
        all_ids = [int(pid) for pid in projects if str(pid).isdigit()]
        project_id = str(max(all_ids) + 1) if all_ids else "1"
        projects[project_id] = {
            "id": project_id,
            "name": get_ctx(context, "project_create_name", "Новый проект"),
            "pass": text,
            "author": username,
            "admin": join_users(get_ctx(context, "project_create_admins", [username])),
            "user": join_users(get_ctx(context, "project_create_users", [])),
            "date_create": str(today()),
        }
        save_project(project_id)
        for item in SYSTEM_TASK_SEED:
            task_id = next_task_id(project_id)
            key = task_key(project_id, task_id)
            tasks[key] = {
                "project": project_id,
                "id": task_id,
                "level": item["level"],
                "title": item["title"],
                "description": item["description"],
                "source": item["source"],
                "reward_type": item["reward_type"],
                "reward_value": item["reward_value"],
                "status": STATUS_AVAILABLE,
                "author": username,
                "date": str(today()),
            }
            save_task(key)
        clear_temp_flow(username, context)
        set_current_role_project(context, ROLE_ADMIN, project_id)
        await update.message.reply_text(f"Проект создан: {projects[project_id]['name']}")
        return

    if state == STATE_PROJECT_EDIT_PASSWORD:
        project_id = get_current_project_id(context)
        project = projects.get(project_id)
        if not project or str(text) != str(project.get("pass", "")):
            await update.message.reply_text("Неверный пароль проекта.")
            return
        action = get_ctx(context, "project_edit_action")
        if action == "name":
            user_states[username] = STATE_PROJECT_EDIT_NAME
            await update.message.reply_text("Введите новое имя проекта:")
        elif action == "admins":
            user_states[username] = STATE_PROJECT_EDIT_ADMINS
            await update.message.reply_text(f"Текущие админы: {project.get('admin', '') or '—'}\nВведите новый полный список админов через |:")
        elif action == "users":
            user_states[username] = STATE_PROJECT_EDIT_USERS
            await update.message.reply_text(f"Текущие юзеры: {project.get('user', '') or '—'}\nВведите новый полный список юзеров через |:")
        else:
            await update.message.reply_text("Неизвестное действие.")
        return

    if state == STATE_PROJECT_EDIT_NAME:
        project_id = get_current_project_id(context)
        projects[project_id]["name"] = text
        save_project(project_id)
        clear_temp_flow(username, context)
        set_current_role_project(context, ROLE_ADMIN, project_id)
        await update.message.reply_text("Имя проекта обновлено.")
        return

    if state == STATE_PROJECT_EDIT_ADMINS:
        project_id = get_current_project_id(context)
        projects[project_id]["admin"] = join_users(split_users(text.replace(",", "|")))
        save_project(project_id)
        clear_temp_flow(username, context)
        set_current_role_project(context, ROLE_ADMIN, project_id)
        await update.message.reply_text("Список админов обновлён.")
        return

    if state == STATE_PROJECT_EDIT_USERS:
        project_id = get_current_project_id(context)
        projects[project_id]["user"] = join_users(split_users(text.replace(",", "|")))
        save_project(project_id)
        clear_temp_flow(username, context)
        set_current_role_project(context, ROLE_ADMIN, project_id)
        await update.message.reply_text("Список юзеров обновлён.")
        return

    await update.message.reply_text("Не понял сообщение. Используй меню или Re/start.")


# ================= CALLBACK HANDLER =================
async def global_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    username = normalize_username(query.from_user.username)
    ensure_user(username)

    if data == "restart_role":
        clear_temp_flow(username, context)
        await start(update, context)
        return

    if data == "main_menu":
        await show_main_menu(update, context)
        return

    if data == "help":
        await show_help(update, context)
        return

    if data == "role_admin":
        users[username]["role"] = ROLE_ADMIN
        save_user(username)
        await show_role_projects(update, context, ROLE_ADMIN)
        return

    if data == "role_user":
        users[username]["role"] = ROLE_USER
        save_user(username)
        await show_role_projects(update, context, ROLE_USER)
        return

    if data.startswith("project_pick_"):
        _, _, role, project_id = data.split("_", 3)
        if not user_has_project_role(username, project_id, role):
            await query.message.reply_text("У тебя нет доступа к этому проекту для выбранной роли.")
            return
        set_ctx(context, "selected_project_id", project_id)
        set_ctx(context, "selected_role", role)
        if role == ROLE_ADMIN:
            user_states[username] = STATE_PROJECT_PASSWORD
            await query.message.reply_text(f"Введи пароль проекта «{get_project_name(project_id)}»:")
            return
        user_states.pop(username, None)
        set_current_role_project(context, role, project_id)
        await show_main_menu(update, context)
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

    if data.startswith("series_fix_"):
        doing_id = data.replace("series_fix_", "", 1)
        await mark_series_fixed(update, context, doing_id)
        return

    if data.startswith("series_remind_"):
        doing_id = data.replace("series_remind_", "", 1)
        await remind_series_tomorrow(update, context, doing_id)
        return

    if data == "admin_offers":
        await show_admin_offers(update, context)
        return

    if data.startswith("admin_approve_offer_"):
        project_id = get_current_project_id(context)
        task_id = data.replace("admin_approve_offer_", "", 1)
        key = task_key(project_id, task_id)
        if key in tasks:
            tasks[key]["status"] = STATUS_AVAILABLE
            save_task(key)
        await show_admin_offers(update, context)
        return

    if data.startswith("admin_reject_offer_"):
        project_id = get_current_project_id(context)
        task_id = data.replace("admin_reject_offer_", "", 1)
        key = task_key(project_id, task_id)
        if key in tasks:
            tasks[key]["status"] = STATUS_REJECTED
            save_task(key)
        await show_admin_offers(update, context)
        return

    if data == "admin_stats":
        await show_admin_stats(update, context)
        return

    if data.startswith("admin_stats_user_"):
        target = data.replace("admin_stats_user_", "", 1)
        project_id = get_current_project_id(context)
        text = build_stats_text(project_id, target)
        markup = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("← Назад", callback_data="admin_stats")],
                [InlineKeyboardButton("В главное меню", callback_data="main_menu")],
            ]
        )
        await send_or_edit(update, text[:4096], reply_markup=markup)
        return

    if data == "admin_pay":
        project_id = get_current_project_id(context)
        users_list = sorted(set(get_project_users(project_id)))
        if not users_list:
            await query.message.reply_text("В проекте нет пользователей для выплаты.")
            return
        buttons = [[InlineKeyboardButton(f"@{item}", callback_data=f"admin_pay_user_{item}")] for item in users_list]
        buttons.append([InlineKeyboardButton("В главное меню", callback_data="main_menu")])
        await send_or_edit(update, "Выбери пользователя для записи выплаты/долга:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("admin_pay_user_"):
        target = data.replace("admin_pay_user_", "", 1)
        set_ctx(context, "payment_target", target)
        set_ctx(context, "payment_project", get_current_project_id(context))
        user_states[username] = STATE_ADMIN_PAY_AMOUNT
        await query.message.reply_text("Введи сумму. Как введёшь, так и запишем в ledger (знак не инвертируется):")
        return

    if data == "admin_add_task":
        user_states[username] = STATE_ADMIN_ADD_TITLE
        await query.message.reply_text("Введи название нового задания:")
        return

    if data == "admin_delete_task":
        await show_admin_delete_tasks(update, context)
        return

    if data.startswith("admin_archive_task_"):
        project_id = get_current_project_id(context)
        task_id = data.replace("admin_archive_task_", "", 1)
        key = task_key(project_id, task_id)
        if key in tasks and tasks[key].get("status") == STATUS_AVAILABLE:
            tasks[key]["status"] = STATUS_ARCHIVED
            save_task(key)
        await show_admin_delete_tasks(update, context)
        return

    if data == "admin_end_series":
        project_id = get_current_project_id(context)
        active_series = [item for item in series_records if item.get("project") == project_id and item.get("status") in {SERIES_STATUS_ACTIVE, SERIES_STATUS_AT_RISK}]
        if not active_series:
            await query.message.reply_text("Нет активных серий в проекте.")
            return
        active_series.sort(key=lambda item: (item.get("username", ""), item.get("start_date", "")))
        buttons = [[InlineKeyboardButton(f"@{item['username']} / {item['start_date']}", callback_data=f"admin_end_series_user_{item['username']}")] for item in active_series]
        buttons.append([InlineKeyboardButton("В главное меню", callback_data="main_menu")])
        await send_or_edit(update, "Выбери пользователя для закрытия серии:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("admin_end_series_user_"):
        target = data.replace("admin_end_series_user_", "", 1)
        set_ctx(context, "payment_target", target)
        user_states[username] = STATE_ADMIN_END_SERIES_CONFIRM
        await query.message.reply_text(f"Подтверди закрытие текущей серии для @{target}. Напиши ДА.")
        return

    if data == "admin_new_project":
        user_states[username] = STATE_PROJECT_CREATE_NAME
        await query.message.reply_text("Дайте имя новому проекту:")
        return

    if data == "admin_edit_project":
        await show_project_edit_menu(update, context)
        return

    if data == "edit_project_name":
        set_ctx(context, "project_edit_action", "name")
        user_states[username] = STATE_PROJECT_EDIT_PASSWORD
        await query.message.reply_text("Введите пароль текущего проекта:")
        return

    if data == "edit_project_admins":
        set_ctx(context, "project_edit_action", "admins")
        user_states[username] = STATE_PROJECT_EDIT_PASSWORD
        await query.message.reply_text("Введите пароль текущего проекта:")
        return

    if data == "edit_project_users":
        set_ctx(context, "project_edit_action", "users")
        user_states[username] = STATE_PROJECT_EDIT_PASSWORD
        await query.message.reply_text("Введите пароль текущего проекта:")
        return


# ================= POST INIT =================
async def post_init(application):
    asyncio.create_task(_sheets_worker())
    await application.bot.set_my_commands([
        BotCommand("start", "Запустить / сменить роль и проект"),
    ])
    print("[Queue] Sheets worker started")


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
