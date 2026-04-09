import os
import datetime
from datetime import timedelta
from collections import defaultdict
import json
import time
import asyncio
import concurrent.futures
import threading

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton
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

# ================= SHEETS WRITE QUEUE =================
# Все записи в Google Sheets идут через очередь.
# Пользователь получает ответ немедленно; Sheets пишутся в фоне.
_sheets_queue    = []            # pending-задачи
_sheets_lock     = threading.Lock()
_sheets_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=3, thread_name_prefix="sheets"
)

def enqueue(func):
    """Добавить blocking-задачу в очередь (thread-safe, любой контекст)."""
    with _sheets_lock:
        _sheets_queue.append(func)

async def _sheets_worker():
    """Фоновая корутина: собирает задачи пачками за 300 мс, пишет в thread pool."""
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(0.3)
        with _sheets_lock:
            batch = _sheets_queue.copy()
            _sheets_queue.clear()
        if batch:
            await loop.run_in_executor(
                _sheets_executor,
                lambda b=batch: [f() for f in b]
            )

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USERNAME = "Lbimova"
KOSTYA_USERNAMES = ["kxstik_smerch", "babushka_ira_lub", "nemovl4"]
GOOGLE_SHEET_NAME = "Motivation_Log"

# ================= CONSTANTS =================
STATUS_AVAILABLE = "AVAILABLE"
STATUS_OFFERED = "OFFERED"
STATUS_SUBMITTED = "SUBMITTED"
STATUS_APPROVED = "APPROVED"
STATUS_REJECTED = "REJECTED"
STATUS_COMPLETED = "COMPLETED"
STATUS_DONE = "DONE"
STATUS_ARCHIVED = "ARCHIVED"

SOURCE_SYSTEM = "SYSTEM"
SOURCE_USER = "USER"

# Постоянная нижняя кнопка навигации (ReplyKeyboard)
MAIN_MENU_REPLY_KB = ReplyKeyboardMarkup(
    [[KeyboardButton("🏠 Главное меню"), KeyboardButton("Re/start")]],
    resize_keyboard=True,
    is_persistent=True
)

ROLE_MAMA = "MAMA"
ROLE_KOSTYA = "KOSTYA"
ROLE_GUEST = "GUEST"

LEVEL_COEFS = {
    "2": 0.5,
    "3": 0.4
}

# ================= GOOGLE INIT =================
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

def init_sheets():
    global tasks_ws, users_ws, ledger_ws
    
    # Открываем таблицу один раз
    spreadsheet = gc.open(GOOGLE_SHEET_NAME)

    try:
        tasks_ws = spreadsheet.worksheet("tasks")
    except:
        tasks_ws = spreadsheet.add_worksheet(title="tasks", rows="1000", cols="10")
        tasks_ws.append_row(["id","title","description","source","reward_type","reward_value","status","executor","date"])
    
    time.sleep(1.2) # Пауза для обхода лимита 429

    try:
        users_ws = spreadsheet.worksheet("users")
    except:
        users_ws = spreadsheet.add_worksheet(title="users", rows="1000", cols="10")
        users_ws.append_row(["username","series","bank_counter","last_date","role"])

    time.sleep(1.2)

    try:
        ledger_ws = spreadsheet.worksheet("ledger")
    except:
        ledger_ws = spreadsheet.add_worksheet(title="ledger", rows="1000", cols="10")
        ledger_ws.append_row(["timestamp","username","amount","type","comment"])

init_sheets()

# ================= DATA CONTAINERS =================
users = {}
tasks = {}
ledger = []
task_counter = 1
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
            time.sleep(1.2)

def get_balance(username):
    return sum(float(x["amount"]) for x in ledger if x["username"] == username)

def load_data():
    global tasks, users, ledger, task_counter

    # TASKS
    time.sleep(1.2)
    rows = tasks_ws.get_all_records()
    for r in rows:
        tasks[str(r["id"])] = r

    # USERS
    time.sleep(1.2)
    rows = users_ws.get_all_records()
    for r in rows:
        uname = r["username"]
        users[uname] = {
            "series": int(r["series"]) if r["series"] else 0,
            "bank_counter": int(r["bank_counter"]) if r["bank_counter"] else 0,
            "last_date": datetime.date.fromisoformat(r["last_date"]) if r["last_date"] else None,
            "role": r.get("role", ROLE_GUEST) or ROLE_GUEST
        }

    # LEDGER
    time.sleep(1.2)
    rows = ledger_ws.get_all_records()
    ledger = rows

    if tasks:
        task_counter = max(int(k) for k in tasks.keys() if str(k).isdigit()) + 1
    else:
        task_counter = 1

load_data()

# ================= HELPERS =================
def get_role(username: str) -> str:
    """Определяет роль по username — единственный источник правды."""
    if username == ADMIN_USERNAME:
        return ROLE_MAMA
    if username in KOSTYA_USERNAMES:
        return ROLE_KOSTYA
    return ROLE_GUEST

# ================= LOGGING & MONEY =================
def log_event(username, event_type, amount=0, balance=0, comment=""):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [now, username, amount, event_type, comment]
    enqueue(lambda r=row: safe_append(ledger_ws, r))
    ledger.append({
        "username": username,
        "amount": amount,
        "type": event_type,
        "timestamp": now,
        "comment": comment
    })

def add_money(username, amount, event_type, comment=""):
    log_event(username, event_type, amount, get_balance(username), comment)

def save_user(username):
    """Сохраняет пользователя в users_ws через фоновую очередь."""
    user = users[username]
    last_date_str = user["last_date"].isoformat() if user["last_date"] else ""
    new_row = [
        username,
        user.get("series", 0),
        user.get("bank_counter", 0),
        last_date_str,
        user.get("role", ROLE_GUEST)
    ]
    def _write(uname=username, row=new_row):
        try:
            cell = users_ws.find(uname)
            users_ws.update(f"A{cell.row}:E{cell.row}", [row])
        except Exception:
            safe_append(users_ws, row)
    enqueue(_write)

# ================= SERIES LOGIC =================
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
            # Серия продолжается (страховка не сбрасывает), last_date обновляем
            user["last_date"] = today()
            save_user(username)
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

    save_user(username)  # Сохраняем серию и last_date в Google Sheets
    return None
# ================= CONTENT =================
LEVEL_TEXTS = {
    "1": ["Посуда", "Лоток", "Мусор", "Стол", "Убрать часть комнаты", "Магазин не ночью"],
    "1+": ["Не опоздать в школу"],
    "1++": ["Разбор темы по русскому (30 р. фикс.)"],
    "2": ["Русский — введите баллы ЦТ (коэфф. 0.5)"],
    "3": ["Английский — введите баллы ЦТ (коэфф. 0.4)"],
    "4": ["Математика — введите баллы ЦТ (≤20:15 р., >20:40 р.)"]
}

LEVEL_COEFFICIENT = {"2": 0.5, "3": 0.4}

# ================= KEYBOARDS =================
def get_main_menu(role):
    keyboard = []
    keyboard.append([InlineKeyboardButton("Доступные задания", callback_data="tasks")])
    keyboard.append([InlineKeyboardButton("Справка", callback_data="help")])

    if role == ROLE_KOSTYA:
        keyboard.append([InlineKeyboardButton("Предложить задание", callback_data="offer_job")])
        keyboard.append([InlineKeyboardButton("Статистика", callback_data="kostya_stats")])

    if role == ROLE_MAMA:
        keyboard.append([InlineKeyboardButton("Непроверенные", callback_data="mama_pending")])
        keyboard.append([InlineKeyboardButton("Предложенные работы", callback_data="mama_offers")])
        keyboard.append([InlineKeyboardButton("Статистика", callback_data="mama_stats")])
        keyboard.append([InlineKeyboardButton("Оплатить", callback_data="mama_pay")])
        keyboard.append([InlineKeyboardButton("Удалить задание", callback_data="mama_delete_task")])

    return InlineKeyboardMarkup(keyboard)

def mama_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Непроверенные", callback_data="mama_pending")],
        [InlineKeyboardButton("Предложенные работы", callback_data="mama_offers")],
        [InlineKeyboardButton("Выполненные задания", callback_data="mama_done")],
        [InlineKeyboardButton("Добавить задание", callback_data="mama_add_task")],
        [InlineKeyboardButton("Удалить доступные задания", callback_data="mama_delete_task")],
        [InlineKeyboardButton("Статистика", callback_data="mama_stats")],
        [InlineKeyboardButton("Оплатить", callback_data="mama_pay")],
        [InlineKeyboardButton("⛔ Прервать сессию", callback_data="mama_end_session")],
        [InlineKeyboardButton("В главное меню", callback_data="main_menu")]
    ])

# ================= CORE HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if not username:
        await update.message.reply_text("Ваш username не определён")
        return

    role = get_role(username)

    if username not in users:
        users[username] = {"series": 0, "bank_counter": 0, "last_date": None, "role": role}
        safe_append(users_ws, [username, 0, 0, "", role])

    users[username]["role"] = role
    # Устанавливаем постоянную нижнюю кнопку навигации
    await update.message.reply_text(
        "Используй кнопку ниже для быстрого возврата в меню:",
        reply_markup=MAIN_MENU_REPLY_KB
    )
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    # Роль из памяти, но если пользователь не загружен — определяем по username
    role = users.get(username, {}).get("role") or get_role(username)

    if role == ROLE_MAMA:
        text = "Меню Мамы:"
        markup = mama_menu_keyboard()
    elif role == ROLE_KOSTYA:
        text = "Меню Кости:"
        markup = get_main_menu(ROLE_KOSTYA)
    else:
        text = "Меню Гостя:"
        markup = get_main_menu(ROLE_GUEST)

    # Определяем источник вызова: callback или обычное сообщение
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)

async def help_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Правила:\n"
        "1. Каждый день выполняй минимум одно дело.\n"
        "2. Можешь предлагать задания.\n"
        "3. Пропуск дня сбрасывает серию.\n"
        "4. Задания: Ур.1 (1,5р), Ур.1+ (2,5р), Ур.1++ (30р), Ур.2 (коэф.0,5), Ур.3 (коэф.0,4), Ур.4 (15/40р).\n"
        "5. Серии: 5 дней (+10р), 9 дней (+25р).\n"
        "Серия 14 дней. Делай хоть что-то каждый день.\n"
        "Без форс-мажоров выплата в конце серии."
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("В главное меню", callback_data="main_menu")]])
    # Работает и из /rules-команды, и из inline-кнопки
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)
# ================= MAMA SPECIFIC HANDLERS =================
async def show_pending_for_mama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending = [t for t in tasks.values() if t["status"] in [STATUS_SUBMITTED, STATUS_OFFERED]]
    if not pending:
        await update.callback_query.edit_message_text("Нет непроверенных заданий", reply_markup=mama_menu_keyboard())
        return
    text = "Непроверенные задания:\n"
    buttons = []
    for t in pending:
        label_type = "оффер" if t["status"] == STATUS_OFFERED else "выполнено"
        text += (f"{t['id']}. {t.get('title', '—')} "
                 f"({label_type}) — {t.get('executor', '?')} — {t.get('reward_value', 0)} р.\n")
        buttons.append([
            InlineKeyboardButton(f"✓ {t['id']}", callback_data=f"mama_approve_{t['id']}"),
            InlineKeyboardButton(f"✗ {t['id']}", callback_data=f"mama_reject_{t['id']}")
        ])
    buttons.append([InlineKeyboardButton("В главное меню", callback_data="main_menu")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

async def show_offers_for_mama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    offers = [t for t in tasks.values() if t["status"] == STATUS_OFFERED]
    if not offers:
        await update.callback_query.edit_message_text("Нет предложенных заданий", reply_markup=mama_menu_keyboard())
        return
    text = "Предложенные задания:\n"
    buttons = []
    for t in offers:
        text += f"{t['id']}. {t['title']} — предложено {t['reward_value']} р.\n"
        buttons.append([InlineKeyboardButton(f"Одобрить {t['id']}", callback_data=f"mama_approve_{t['id']}")])
    buttons.append([InlineKeyboardButton("В главное меню", callback_data="main_menu")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

async def show_mama_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now()
    total_earned = sum(float(l["amount"]) for l in ledger if datetime.datetime.strptime(l["timestamp"], "%Y-%m-%d %H:%M:%S") >= now - timedelta(days=14))
    await update.callback_query.edit_message_text(f"Статистика за 14 дней:\nВсего начислено: {total_earned} р.", reply_markup=mama_menu_keyboard())

# ================= COMPLETION LOGIC =================
async def complete_task(username, level, idx, reward):
    task_id = f"{level}_{idx}_{str(datetime.datetime.now().timestamp())}"
    title = LEVEL_TEXTS[level][idx-1] if level in ["1", "1+", "1++"] else LEVEL_TEXTS[level][0]
    tasks[task_id] = {
        "id": task_id,
        "title": title,
        "description": "",
        "source": SOURCE_SYSTEM,
        "reward_type": "FIXED" if level in ["1", "1+", "1++", "4"] else "COEF",
        "reward_value": reward,
        "status": STATUS_COMPLETED,
        "executor": username,
        "date": str(today())
    }
    # 9 колонок: id, title, description, source, reward_type, reward_value, status, executor, date
    safe_append(tasks_ws, [
        task_id,
        title,
        "",
        SOURCE_SYSTEM,
        tasks[task_id]["reward_type"],
        reward,
        STATUS_COMPLETED,
        username,
        str(today())
    ])
    add_money(username, reward, "TASK_COMPLETE", comment=f"Level {level} Task {idx}")

    # Математический банк: level 4 → bank_counter++, каждые 3 → +15 р.
    if level == "4" and username in users:
        users[username]["bank_counter"] = users[username].get("bank_counter", 0) + 1
        if users[username]["bank_counter"] % 3 == 0:
            add_money(username, 15, "MATH_BANK",
                      comment=f"Банк математики: {users[username]['bank_counter']} выполнений")
        save_user(username)  # Сохраняем обновлённый bank_counter

# ================= TEXT & CALLBACK HANDLER =================
async def global_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global task_counter
    text = update.message.text
    username = update.effective_user.username
    state = user_states.get(username)

    # ReplyKeyboard: постоянная кнопка возврата в главное меню
    if text == "🏠 Главное меню":
        user_states.pop(username, None)  # сбрасываем любой FSM-стейт
        await show_main_menu(update, context)
        return
    elif text == "Re/start":
        await start(update, context)
        return

    # ЛОГИКА "Мама /номер сумма"
    if text.startswith("Мама /"):
        try:
            parts = text.split()
            tid, rew = parts[1].replace("/", ""), float(parts[2])
            if tid in tasks:
                tasks[tid]["status"], tasks[tid]["reward_value"] = STATUS_AVAILABLE, rew
                await update.message.reply_text(f"Задание {tid} одобрено на {rew} р.")
            return
        except: pass

    if state == "OFFER_TITLE":
        context.user_data["off_t"] = text
        user_states[username] = "OFFER_REWARD"
        await update.message.reply_text("Награда за задание:")
    elif state == "OFFER_REWARD":
        global task_counter
        try:
            tasks[str(task_counter)] = {"id": task_counter, "title": context.user_data["off_t"], "reward_value": float(text), "status": STATUS_OFFERED, "added_by": username}
            task_counter += 1
            await update.message.reply_text("Оффер отправлен!")
            user_states.pop(username)
        except: await update.message.reply_text("Введите число!")
    elif state == "MAMA_PAY":
        try:
            add_money("kxstik_smerch", -float(text), "PAYMENT", "Выплата наличных")
            await update.message.reply_text(f"Оплата {text} р. записана.")
            user_states.pop(username)
        except: await update.message.reply_text("Введите число!")
    elif state and state.startswith("INPUT_CT_"):
        try:
            score = float(text)
            lvl = state.split("_")[2]
            rew = score * LEVEL_COEFFICIENT.get(lvl, 1) if lvl != "4" else (15 if score <= 20 else 40)
            await complete_task(username, lvl, 0, rew)
            update_series(username)
            await update.message.reply_text(f"Записано! +{rew} р.")
            user_states.pop(username)
        except: await update.message.reply_text("Ошибка в баллах!")
    elif state == "MAMA_ADD_TITLE":
        context.user_data["mama_task_title"] = text
        user_states[username] = "MAMA_ADD_REWARD"
        await update.message.reply_text("Награда за задание (рублей):")
    elif state == "MAMA_ADD_REWARD":
        try:
            reward_val = float(text)
            tid = str(task_counter)
            tasks[tid] = {
                "id": tid,
                "title": context.user_data.get("mama_task_title", "Без названия"),
                "description": "",
                "source": SOURCE_SYSTEM,
                "reward_type": "FIXED",
                "reward_value": reward_val,
                "status": STATUS_AVAILABLE,
                "executor": "",
                "date": str(today())
            }
            safe_append(tasks_ws, [
                tid,
                tasks[tid]["title"],
                "",
                SOURCE_SYSTEM,
                "FIXED",
                reward_val,
                STATUS_AVAILABLE,
                "",
                str(today())
            ])
            task_counter += 1
            user_states.pop(username)
            await update.message.reply_text(
                f'Задание "{tasks[tid]["title"]}" добавлено ({reward_val} р.).'
            )
        except ValueError:
            await update.message.reply_text("Введите число (сумму награды):")

async def global_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    username = query.from_user.username

    if data == "main_menu": await show_main_menu(update, context)
    elif data == "help": await help_text(update, context)
    elif data == "tasks":
        kb = [[InlineKeyboardButton(f"Уровень {l}", callback_data=f"stask_{l}")] for l in ["1", "1+", "1++", "2", "3", "4"]]
        await query.edit_message_text("Выбери уровень:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("stask_"):
        lvl = data.split("_")[1]
        kb = [[InlineKeyboardButton(t, callback_data=f"cmpl_{lvl}_{i+1}")] for i, t in enumerate(LEVEL_TEXTS[lvl])]
        kb.append([InlineKeyboardButton("← Назад к уровням", callback_data="tasks")])
        await query.edit_message_text(f"Задания уровня {lvl}:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("cmpl_"):
        _, lvl, idx = data.split("_")
        if lvl in ["2", "3", "4"]:
            user_states[username] = f"INPUT_CT_{lvl}_{idx}"
            await query.message.reply_text("Введите баллы ЦТ:")
        else:
            reward = 1.5 if lvl == "1" else 2.5 if lvl == "1+" else 30
            await complete_task(username, lvl, int(idx), reward)
            msg = update_series(username)
            await query.message.reply_text(f"Готово! +{reward} р. {msg if msg else ''}")
    elif data == "offer_job":
        user_states[username] = "OFFER_TITLE"
        await query.message.reply_text("Название вашего задания:")
    elif data == "kostya_stats":
        await show_user_stats(update, context)
    elif data.startswith("mama_"):
        # Мама-кнопки
        if data == "mama_pending": await show_pending_for_mama(update, context)
        elif data == "mama_offers": await show_offers_for_mama(update, context)
        elif data == "mama_stats": await show_mama_stats(update, context)
        elif data == "mama_pay":
            user_states[username] = "MAMA_PAY"
            await query.message.reply_text("Сумма выплаты:")
        elif data == "mama_done": await show_done_for_mama(update, context)
        elif data == "mama_add_task": await show_add_task_for_mama(update, context)
        elif data == "mama_delete_task": await show_delete_task_for_mama(update, context)
        elif data.startswith("mama_approve_"):
            tid = data.replace("mama_approve_", "", 1)
            if tid not in tasks:
                await update.callback_query.answer("Задание не найдено")
            else:
                t = tasks[tid]
                if t["status"] == STATUS_SUBMITTED:
                    # Выполненное задание: одобряем → APPROVED + деньги + серия
                    t["status"] = STATUS_APPROVED
                    executor = t.get("executor", "")
                    if executor and executor in users:
                        add_money(executor, float(t.get("reward_value", 0)),
                                  "TASK_REWARD", comment=f"Одобрено: {t.get('title', '')}")
                        update_series(executor)
                    await update.callback_query.answer(f"✓ Задание одобрено, +{t.get('reward_value', 0)} р.")
                    await show_pending_for_mama(update, context)
                elif t["status"] == STATUS_OFFERED:
                    # Оффер от Кости: одобряем → AVAILABLE (теперь доступно для выполнения)
                    t["status"] = STATUS_AVAILABLE
                    await update.callback_query.answer(f"✓ Оффер одобрен — задание доступно для выполнения")
                    await show_pending_for_mama(update, context)
                else:
                    await update.callback_query.answer("Задание уже обработано")
        elif data.startswith("mama_reject_"):
            tid = data.replace("mama_reject_", "", 1)
            if tid not in tasks:
                await update.callback_query.answer("Задание не найдено")
            else:
                tasks[tid]["status"] = STATUS_REJECTED
                await update.callback_query.answer(f"✗ Задание {tid} отклонено")
                await show_pending_for_mama(update, context)
        elif data.startswith("mama_del_"):
            tid = data.replace("mama_del_", "", 1)
            if tid in tasks and tasks[tid].get("status") == STATUS_AVAILABLE:
                # Мягкое удаление: задание скрывается из списка, история сохраняется
                tasks[tid]["status"] = STATUS_ARCHIVED
                await update.callback_query.answer(f"Задание {tid} перемещено в архив")
                await show_delete_task_for_mama(update, context)
            else:
                await update.callback_query.answer("Задание не найдено или уже недоступно")

# ================= MAMA EXTRA HANDLERS =================
async def show_done_for_mama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает все выполненные задания."""
    done = [t for t in tasks.values() if t.get("status") == STATUS_COMPLETED]
    if not done:
        await update.callback_query.edit_message_text(
            "Нет выполненных заданий",
            reply_markup=mama_menu_keyboard()
        )
        return
    lines = [f"{t['id']}. {t.get('title', '—')} — {t.get('executor', '—')} — {t.get('date', '—')}"
             for t in done[-20:]]  # Последние 20, чтобы не переполнить сообщение
    text = "Выполненные задания (последние 20):\n" + "\n".join(lines)
    await update.callback_query.edit_message_text(
        text[:4000],  # Telegram limit
        reply_markup=mama_menu_keyboard()
    )

async def show_add_task_for_mama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запускает FSM добавления задания мамой."""
    username = update.callback_query.from_user.username
    user_states[username] = "MAMA_ADD_TITLE"
    await update.callback_query.message.reply_text(
        "Введите название нового задания:"
    )

async def show_delete_task_for_mama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает доступные задания с кнопками удаления."""
    available = [t for t in tasks.values() if t.get("status") == STATUS_AVAILABLE]
    if not available:
        await update.callback_query.edit_message_text(
            "Нет доступных заданий для удаления",
            reply_markup=mama_menu_keyboard()
        )
        return
    text = "Выберите задание для удаления:\n"
    buttons = []
    for t in available:
        label = f"{t['id']}. {t.get('title', '—')} — {t.get('reward_value', 0)} р."
        text += label + "\n"
        buttons.append([
            InlineKeyboardButton(f"Удалить {t['id']}", callback_data=f"mama_del_{t['id']}")
        ])
    buttons.append([InlineKeyboardButton("В главное меню", callback_data="main_menu")])
    await update.callback_query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(buttons)
    )

# ================= USER STATS =================
def _build_stats_text(target_username: str) -> str:
    """Строит текст расширенной статистики для пользователя."""
    user = users.get(target_username, {})
    series        = user.get("series", 0)
    session_start = user.get("session_start")
    bank          = user.get("bank_counter", 0)
    balance       = get_balance(target_username)
    ss_str = session_start.strftime("%d.%m.%Y") if session_start else "—"
    ss_iso = str(session_start) if session_start else ""

    # APPROVED задания за текущую сессию
    session_tasks = [
        t for t in tasks.values()
        if t.get("status") == STATUS_APPROVED
        and t.get("executor") == target_username
        and (not ss_iso or str(t.get("date", "")) >= ss_iso)
    ]
    session_tasks.sort(key=lambda t: str(t.get("date", "")))

    # Выплаты за текущую сессию
    session_payouts = [
        e for e in ledger
        if e.get("username") == target_username
        and str(e.get("type", "")).upper() in ("PAYMENT", "PAYOUT")
        and (not ss_iso or str(e.get("timestamp", ""))[:10] >= ss_iso)
    ]

    lines = [f"📊 Статистика @{target_username}"]
    lines.append(f"🗓 Начало сессии: {ss_str}")
    lines.append(f"🔥 Серия: {series} дн. (завершено дней)")

    # Список заданий
    lines.append("\n📋 Выполненные задания (одобренные):")
    if session_tasks:
        total_tasks_sum = 0.0
        for t in session_tasks:
            r = float(t.get("reward_value", 0))
            total_tasks_sum += r
            lines.append(f"  • {t.get('date', '')} — {t.get('title', '—')} — +{r:.1f} р.")
        lines.append(f"  ▶ Итого: {len(session_tasks)} заданий, {total_tasks_sum:.1f} р.")
    else:
        lines.append("  Нет одобренных заданий в этой сессии")

    # Список выплат
    lines.append("\n💸 Выплаты:")
    if session_payouts:
        total_paid = 0.0
        for e in session_payouts:
            amt = abs(float(e.get("amount", 0)))
            total_paid += amt
            ts = str(e.get("timestamp", ""))[:10]
            lines.append(f"  • {ts} — {amt:.1f} р.")
        lines.append(f"  ▶ Итого: {len(session_payouts)} выплат, {total_paid:.1f} р.")
    else:
        lines.append("  Нет выплат в этой сессии")

    lines.append(f"\n💼 Остаток: {balance:.1f} р.")
    if bank > 0:
        lines.append(f"📐 Банк математики: {bank} (до бонуса: {3 - bank % 3})")

    return "\n".join(lines)

async def show_user_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Расширенная статистика: сессия, задания, выплаты, баланс, банк."""
    username = update.callback_query.from_user.username
    text = _build_stats_text(username)
    await update.callback_query.edit_message_text(
        text[:4096],
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("В главное меню", callback_data="main_menu")]]
        )
    )

# ================= APPLICATION START =================
async def post_init(application):
    """Запускаем фоновый воркер Sheets-очереди после старта event loop."""
    asyncio.create_task(_sheets_worker())
    print("[Queue] Sheets write worker started")

if __name__ == '__main__':
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://your-app.up.railway.app
    PORT = int(os.getenv("PORT", 8443))

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(global_query_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_text_handler))

    if WEBHOOK_URL:
        # ── Webhook-режим (продакшн) ──────────────────────────────────────
        print(f"[Webhook] port={PORT}  url={WEBHOOK_URL}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
        )
    else:
        # ── Polling-режим (локальная разработка) ──────────────────────────
        print("[Polling] Бот запущен в режиме polling...")
        app.run_polling()

