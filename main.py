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
        users_ws.append_row(["username","series","bank_counter","last_date","role"])

    try:
        ledger_ws = gc.open(GOOGLE_SHEET_NAME).worksheet("ledger")
    except:
        ledger_ws = gc.open(GOOGLE_SHEET_NAME).add_worksheet(title="ledger", rows="1000", cols="10")
        ledger_ws.append_row(["timestamp","username","amount","type","comment"])

init_sheets()

# ================= DATA =================
users = {}
tasks = {}
ledger = []
task_counter = 1
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

ROLE_MAMA = "MAMA"
ROLE_KOSTYA = "KOSTYA"
ROLE_GUEST = "GUEST"

LEVEL_COEFS = {
    "2": 0.5,
    "3": 0.4
}

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

def get_balance(username):
    return sum(x["amount"] for x in ledger if x["username"] == username)

def load_data():
    global tasks, users, ledger, task_counter

    # TASKS
    rows = tasks_ws.get_all_records()
    for r in rows:
        tasks[str(r["id"])] = r

    # USERS
    rows = users_ws.get_all_records()
    for r in rows:
        users[r["username"]] = {
            "series": int(r["series"]),
            "bank_counter": int(r["bank_counter"]),
            "last_date": datetime.date.fromisoformat(r["last_date"]) if r["last_date"] else None,
            "role": r.get("role", ROLE_GUEST)
        }

    # LEDGER
    rows = ledger_ws.get_all_records()
    for r in rows:
        ledger.append(r)

    if tasks:
        task_counter = max(int(k) for k in tasks.keys()) + 1
    else:
        task_counter = 1

load_data()
# ================= LOGGING =================
def log_event(username, event_type, amount=0, balance=0, comment=""):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_append(ledger_ws, [now, username, amount, event_type, comment])
    ledger.append({
        "username": username,
        "amount": amount,
        "type": event_type,
        "timestamp": now,
        "comment": comment
    })

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

# ================= MENU HELPERS =================
def get_main_menu(role):
    keyboard = []

    # Общие кнопки
    keyboard.append([InlineKeyboardButton("Начать сессию", callback_data="start_session")])
    keyboard.append([InlineKeyboardButton("Справка", callback_data="help")])
    keyboard.append([InlineKeyboardButton("Доступные задания", callback_data="show_tasks")])
    keyboard.append([InlineKeyboardButton("Выполненные задания", callback_data="completed_tasks")])

    if role == ROLE_KOSTYA:
        keyboard.append([InlineKeyboardButton("Предложить задание", callback_data="offer_job")])
        keyboard.append([InlineKeyboardButton("Статистика", callback_data="my_stats")])

    if role == ROLE_MAMA:
        keyboard.append([InlineKeyboardButton("Непроверенные", callback_data="pending_tasks")])
        keyboard.append([InlineKeyboardButton("Предложенные работы", callback_data="mama_offers")])
        keyboard.append([InlineKeyboardButton("Статистика", callback_data="all_stats")])
        keyboard.append([InlineKeyboardButton("Оплатить", callback_data="pay_kostya")])
        keyboard.append([InlineKeyboardButton("Удалить задание", callback_data="delete_task")])

    return InlineKeyboardMarkup(keyboard)

HELP_TEXT = (
    "📌 Краткие правила:\n"
    "1. Делай минимум одно задание каждый день. Можно два.\n"
    "2. Можешь предлагать свои задания и вознаграждения.\n"
    "3. Пропуск дня сбрасывает серию.\n"
    "4. Задания:\n"
    "• Уровень 1 (1,5 р.): посуда, лоток, мусор, стол, убрать часть комнаты, магазин не ночью.\n"
    "• Уровень 1+ (2,5 р.): не опоздать в школу. Три дня подряд опоздание — минус 5 р.\n"
    "• Уровень 1++ (30 р. фикс.): разбор темы по русскому.\n"
    "• Уровень 2 (русский) — деньги по коэффициенту 0,5.\n"
    "• Уровень 3 (английский) — деньги по коэффициенту 0,4.\n"
    "• Уровень 4 (математика) — ≤20 баллов: 15 р., >20 баллов: 40 р.\n"
    "5. Серии дают бонусы: 5 дней — +10 р., 9 дней — +25 р.\n"
    "6. Математика: за 3 выполненных задания — +15 р.\n"
    "7. Хорошая оценка (>6) заменяет одно задание.\n"
    "8. Плохая оценка — оплачивается как обычное задание.\n"
    "Главное: серия — 14 дней, делай хоть что-то каждый день."
)

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if not username:
        await update.message.reply_text("Ваш username не определён")
        return

    # Авто-роли
    if username == ADMIN_USERNAME:
        role = ROLE_MAMA
    elif username in KOSTYA_USERNAMES:
        role = ROLE_KOSTYA
    else:
        role = ROLE_GUEST

    if username not in users:
        users[username] = {
            "series": 0,
            "bank_counter": 0,
            "last_date": None,
            "role": role
        }
        safe_append(users_ws, [username, 0, 0, "", role])

    users[username]["role"] = role
    user_states.pop(username, None)
    context.user_data.clear()

    await update.message.reply_text(
        f"Бот готов. Твоя роль: {role}",
        reply_markup=get_main_menu(role)
    )

# ================= MAIN MENU CALLBACK =================
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    username = query.from_user.username
    role = users.get(username, {}).get("role", ROLE_GUEST)
    await query.edit_message_text(
        f"Главное меню ({role})",
        reply_markup=get_main_menu(role)
    )

# ================= FSM START FOR OFFER =================
async def offer_job(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    username = query.from_user.username
    user_states[username] = "OFFER_TITLE"
    await query.edit_message_text("Название задания:")

# ================= TEXT HANDLER WITH FSM =================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if not username:
        return

    # ===== MAIN FSM FOR USER OFFERS =====
    if username in user_states:
        state = user_states[username]

        # 1. Название оффера
        if state == "OFFER_TITLE":
            context.user_data["offer_title"] = update.message.text
            user_states[username] = "OFFER_DESC"
            await update.message.reply_text("Описание задания:")
            return

        # 2. Описание
        elif state == "OFFER_DESC":
            context.user_data["offer_desc"] = update.message.text
            user_states[username] = "OFFER_REWARD"
            await update.message.reply_text("Награда (число):")
            return

        # 3. Награда
        elif state == "OFFER_REWARD":
            global task_counter
            try:
                reward = float(update.message.text)
            except:
                await update.message.reply_text("Ошибка! Введите число.")
                return

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
            safe_append(tasks_ws, [
                task_id,
                context.user_data["offer_title"],
                context.user_data["offer_desc"],
                SOURCE_USER,
                "FIXED",
                reward,
                STATUS_OFFERED,
                username,
                str(today())
            ])

            user_states.pop(username)
            context.user_data.clear()
            await update.message.reply_text("Оффер отправлен на одобрение")
            return
# ================= TASK DISPLAY =================
LEVEL_TEXTS = {
    "1": ["Посуда", "Лоток", "Мусор", "Стол", "Убрать часть комнаты", "Магазин не ночью"],
    "1+": ["Не опоздать в школу"],
    "1++": ["Разбор темы по русскому (30 р. фикс.)"],
    "2": ["Русский — введите баллы ЦТ (коэфф. 0.5)"],
    "3": ["Английский — введите баллы ЦТ (коэфф. 0.4)"],
    "4": ["Математика — введите баллы ЦТ (≤20:15 р., >20:40 р.)"]
}

LEVEL_COEFFICIENT = {"2": 0.5, "3": 0.4}

def format_task_list():
    lines = []
    for lvl in ["1", "1+", "1++"]:
        for idx, txt in enumerate(LEVEL_TEXTS[lvl], 1):
            reward = 1.5 if lvl == "1" else 2.5 if lvl == "1+" else 30
            lines.append(f"Уровень {lvl}, {idx}. {txt} — {reward} р.")
    return "\n".join(lines)

def get_task_buttons(level="1"):
    buttons = []
    if level in ["1", "1+", "1++"]:
        for idx in range(1, len(LEVEL_TEXTS[level]) + 1):
            buttons.append([InlineKeyboardButton(str(idx), callback_data=f"task_{level}_{idx}")])
    else:
        buttons.append([InlineKeyboardButton(f"Уровень {level}", callback_data=f"task_{level}_0")])
    return InlineKeyboardMarkup(buttons)

# ================= TASK CALLBACK =================
async def task_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    username = query.from_user.username
    data = query.data

    parts = data.split("_")
    level = parts[1]
    idx = int(parts[2])

    if level in ["2", "3", "4"]:
        user_states[username] = f"INPUT_CT_{level}_{idx}"
        await query.edit_message_text(f"Введите количество баллов ЦТ для {LEVEL_TEXTS[level][0]}:")
    else:
        reward = 1.5 if level == "1" else 2.5 if level == "1+" else 30
        await complete_task(username, level, idx, reward)
        await query.edit_message_text(f"Задание {level}-{idx} выполнено! +{reward} р.")
        # Обновляем серию
        bonus_msg = update_series(username)
        if bonus_msg:
            await query.message.reply_text(bonus_msg)
        # Показываем главное меню
        role = users[username]["role"]
        await query.message.reply_text("Выберите действие:", reply_markup=get_main_menu(role))

# ================= COMPLETE TASK =================
async def complete_task(username, level, idx, reward):
    task_id = f"{level}_{idx}_{str(datetime.datetime.now().timestamp())}"
    tasks[task_id] = {
        "id": task_id,
        "title": LEVEL_TEXTS[level][idx-1] if level in ["1","1+","1++"] else LEVEL_TEXTS[level][0],
        "level": level,
        "reward": reward,
        "status": STATUS_COMPLETED,
        "executor": username,
        "date": today()
    }
    safe_append(tasks_ws, [
        task_id,
        tasks[task_id]["title"],
        level,
        reward,
        STATUS_COMPLETED,
        username,
        str(today())
    ])
    add_money(username, reward, "TASK_COMPLETE", comment=f"Level {level} Task {idx}")

# ================= CT INPUT HANDLER =================
async def ct_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if username not in user_states:
        return

    state = user_states[username]
    if not state.startswith("INPUT_CT_"):
        return

    parts = state.split("_")
    level = parts[2]
    idx = int(parts[3])

    try:
        score = float(update.message.text)
    except:
        await update.message.reply_text("Введите число!")
        return

    if level in LEVEL_COEFFICIENT:
        reward = score * LEVEL_COEFFICIENT[level]
    elif level == "4":
        reward = 15 if score <= 20 else 40
    else:
        reward = 0

    await complete_task(username, level, idx, reward)
    user_states.pop(username)
    await update.message.reply_text(f"Задание {level}-{idx} выполнено! +{reward} р.")

    bonus_msg = update_series(username)
    if bonus_msg:
        await update.message.reply_text(bonus_msg)

    role = users[username]["role"]
    await update.message.reply_text("Выберите действие:", reply_markup=get_main_menu(role))

# ================= MAMA APPROVE TASK =================
async def mama_approve_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ожидает формат: Мама /номер 00
    text = update.message.text
    if not text.startswith("Мама /"):
        await update.message.reply_text("Неверный формат. Используйте Мама /номер 00")
        return
    try:
        parts = text.split()
        task_id = parts[1]
        reward = float(parts[2])
    except:
        await update.message.reply_text("Неверный формат. Пример: Мама /3 25")
        return

    if task_id in tasks:
        tasks[task_id]["status"] = STATUS_AVAILABLE
        tasks[task_id]["reward"] = reward
        await update.message.reply_text(f"Задание {task_id} одобрено! Вознаграждение: {reward} р.")
        safe_append(tasks_ws, [
            task_id,
            tasks[task_id]["title"],
            tasks[task_id].get("level",""),
            reward,
            STATUS_AVAILABLE,
            tasks[task_id]["executor"],
            str(today())
        ])
    else:
        await update.message.reply_text("Задание не найдено!")

# ================= DELETE TASK =================
async def delete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if users[username]["role"] != ROLE_MAMA:
        await update.message.reply_text("Только Мама может удалять задания.")
        return

    pending_ids = [tid for tid, t in tasks.items() if t["status"] in [STATUS_AVAILABLE, STATUS_OFFERED]]
    keyboard = [[InlineKeyboardButton(tid, callback_data=f"del_{tid}")] for tid in pending_ids]
    await update.message.reply_text("Выберите задание для удаления:", reply_markup=InlineKeyboardMarkup(keyboard))

async def delete_task_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = query.data.replace("del_", "")
    if task_id in tasks:
        del tasks[task_id]
        await query.edit_message_text(f"Задание {task_id} удалено.")
# ================= MENU / ROLES =================
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    role = users.get(username, {}).get("role", "GUEST")
    
    keyboard = []
    
    # Кнопка "В главное меню" всегда доступна
    keyboard.append([InlineKeyboardButton("В главное меню", callback_data="menu_main")])
    
    # Меню для всех
    keyboard.append([InlineKeyboardButton("Справка", callback_data="menu_help")])
    keyboard.append([InlineKeyboardButton("Доступные задания", callback_data="menu_tasks")])
    
    # Дополнительно для Кости
    if role == "KOSTYA":
        keyboard.append([InlineKeyboardButton("Предложить задание", callback_data="menu_offer")])
        keyboard.append([InlineKeyboardButton("Статистика", callback_data="menu_stats")])
    
    # Дополнительно для Мамы
    if role == "MAMA":
        keyboard.append([InlineKeyboardButton("Непроверенные задания", callback_data="menu_pending")])
        keyboard.append([InlineKeyboardButton("Предложенные работы", callback_data="menu_offers")])
        keyboard.append([InlineKeyboardButton("Статистика", callback_data="menu_stats")])
        keyboard.append([InlineKeyboardButton("Оплатить Косте", callback_data="menu_pay")])
        keyboard.append([InlineKeyboardButton("Удалить доступные задания", callback_data="menu_delete")])
    
    await update.message.reply_text("Главное меню:", reply_markup=InlineKeyboardMarkup(keyboard))


# ================= CALLBACK HANDLERS MENU =================
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    username = query.from_user.username
    role = users.get(username, {}).get("role", "GUEST")
    
    if query.data == "menu_main":
        await show_main_menu(update, context)
        return
    
    elif query.data == "menu_help":
        rules_text = (
            "📋 Краткие правила:\n"
            "1. Каждый день минимум одно дело (можно два).\n"
            "2. Можно предлагать свои задания с наградой >1,5 руб.\n"
            "3. Пропуск дня сбрасывает серию.\n"
            "4. Задания:\n"
            "   Уровень 1: посуда, лоток, мусор, стол, убрать часть комнаты, магазин не ночью (1,5 р.)\n"
            "   Уровень 1+: не опоздать в школу (2,5 р., штраф -5 р. за 3 дня подряд опозданий)\n"
            "   Уровень 1++: разбор темы по русскому (30 р. фикс.)\n"
            "   Уровень 2 (русский, коэфф.0,5), Уровень 3 (английский, коэфф.0,4), Уровень 4 (математика 15/40 р.)\n"
            "5. Серии дают бонусы: 5 дней +10 р., 9 дней +25 р.\n"
            "6. Математика: за 3 выполненных задания +15 р.\n"
            "7. Оценка >6 заменяет одно задание.\n"
            "8. Серия длится 14 дней."
        )
        await query.edit_message_text(rules_text)
        return
    
    elif query.data == "menu_tasks":
        await tasks_cmd(update, context)
        return
    
    elif query.data == "menu_offer" and role == "KOSTYA":
        await offer_job(update, context)
        return
    
    elif query.data == "menu_stats":
        await show_stats(update, context)
        return
    
    elif query.data == "menu_pending" and role == "MAMA":
        await show_pending_for_mama(update, context)
        return
    
    elif query.data == "menu_offers" and role == "MAMA":
        await show_offers_for_mama(update, context)
        return
    
    elif query.data == "menu_pay" and role == "MAMA":
        await start_payment_flow(update, context)
        return
    
    elif query.data == "menu_delete" and role == "MAMA":
        await start_delete_task_flow(update, context)
        return


# ================= STATISTICS =================
async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    role = users.get(username, {}).get("role", "GUEST")
    
    now = today()
    start_period = now - datetime.timedelta(days=14)
    
    # Собираем выполненные задания за 14 дней
    user_ledger = [x for x in ledger if x["username"] == username and datetime.datetime.strptime(x.get("timestamp", now.strftime("%Y-%m-%d")), "%Y-%m-%d %H:%M:%S").date() >= start_period]
    
    total = sum(x["amount"] for x in user_ledger)
    msg = f"📊 Статистика за последние 14 дней:\nВсего начислено: {total} р.\n\n"
    
    for x in user_ledger:
        msg += f"{x['timestamp']} - {x['type']} - {x['amount']} р.\n"
    
    if role == "MAMA":
        # статистика по всем пользователям
        total_paid = sum(x["amount"] for x in ledger if x["type"] == "PAYMENT" and datetime.datetime.strptime(x.get("timestamp", now.strftime("%Y-%m-%d")), "%Y-%m-%d %H:%M:%S").date() >= start_period)
        msg += f"\n💰 Оплаты Косте за 14 дней: {total_paid} р."
    
    await update.message.reply_text(msg)


# ================= INTEGRATION CALLBACK =================
app.add_handler(CallbackQueryHandler(menu_handler, pattern="menu_"))


# ================= START BUTTON =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if not username:
        await update.message.reply_text("Ваш username не определён")
        return
    
    # Роли
    if username == "kxstik_smerch" or username == "babushka_ira_lub":
        role = "KOSTYA"
    elif username == "Lbimova":
        role = "MAMA"
    else:
        role = "GUEST"
    
    if username not in users:
        users[username] = {
            "series": 0,
            "bank_counter": 0,
            "last_date": None,
            "role": role
        }
        save_user(username)
    
    await show_main_menu(update, context)
# ================== PART 5: MAMA FLOW, TASK CONFIRMATION, BONUS CALCS ==================

# ===== МЕНЮ МАМЫ =====
def mama_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Непроверенные", callback_data="mama_pending")],
        [InlineKeyboardButton("Предложенные работы", callback_data="mama_offers")],
        [InlineKeyboardButton("Выполненные задания", callback_data="mama_done")],
        [InlineKeyboardButton("Добавить задание", callback_data="mama_add_task")],
        [InlineKeyboardButton("Удалить доступные задания", callback_data="mama_delete_task")],
        [InlineKeyboardButton("Статистика", callback_data="mama_stats")],
        [InlineKeyboardButton("Оплатить", callback_data="mama_pay")],
        [InlineKeyboardButton("В главное меню", callback_data="main_menu")]
    ])

# ===== ОБНОВЛЕНИЕ МЕНЮ ДЛЯ ВСЕХ РОЛЕЙ =====
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if not username:
        await update.message.reply_text("Username не определён")
        return

    # автоматическая роль
    if username in ["kxstik_smerch", "babushka_ira_lub"]:
        users[username]["role"] = "KOSTYA"
    elif username == "Lbimova":
        users[username]["role"] = "MAMA"
    else:
        users[username]["role"] = "GUEST"

    role = users[username]["role"]

    if role == "MAMA":
        await update.message.reply_text(
            "Меню Мамы:", reply_markup=mama_menu_keyboard()
        )
    elif role == "KOSTYA":
        await update.message.reply_text(
            "Меню Кости:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Доступные задания", callback_data="tasks")],
                [InlineKeyboardButton("Предложить задание", callback_data="offer_job")],
                [InlineKeyboardButton("Статистика", callback_data="kostya_stats")],
                [InlineKeyboardButton("В главное меню", callback_data="main_menu")],
                [InlineKeyboardButton("Справка", callback_data="help")]
            ])
        )
    else:  # GUEST
        await update.message.reply_text(
            "Меню Гостя:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Доступные задания", callback_data="tasks")],
                [InlineKeyboardButton("В главное меню", callback_data="main_menu")],
                [InlineKeyboardButton("Справка", callback_data="help")]
            ])
        )

# ===== СПРАВКА =====
async def help_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Правила:\n"
        "1. Каждый день выполняй минимум одно дело (можно два).\n"
        "2. Можешь предлагать задания с собственной наградой.\n"
        "3. Пропуск дня сбрасывает серию.\n"
        "4. Задания:\n"
        "   Уровень 1 (простое, 1,5 р.): посуда, лоток, мусор, стол, часть комнаты, магазин.\n"
        "   Уровень 1+ (2,5 р.): не опоздать в школу; три опоздания подряд — минус 5 р.\n"
        "   Уровень 1++ (30 р. фикс.): разбор темы по русскому.\n"
        "   Уровень 2 (русский ЦТ, коэфф.0,5), Уровень 3 (английский ЦТ, коэфф.0,4), Уровень 4 (математика, ≤20 баллов — 15 р., >20 — 40 р.).\n"
        "5. Нельзя более 2 дней подряд делать только лёгкие или средние задания.\n"
        "6. Серии дают бонусы: 5 дней — +10 р., 9 дней — +25 р.\n"
        "7. Математика даёт накопительный бонус: за 3 выполненных задания — +15 р.\n"
        "8. Хорошая оценка (>6) заменяет одно задание.\n"
        "Главное: серия 14 дней. Делай хоть что-то каждый день."
    )
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("В главное меню", callback_data="main_menu")]]))

# ===== ОБРАБОТКА КНОПОК МАМЫ =====
async def mama_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    username = query.from_user.username
    role = users[username]["role"]

    if role != "MAMA":
        await query.edit_message_text("Эта кнопка только для Мамы")
        return

    data = query.data

    if data == "main_menu":
        await show_main_menu(update, context)
        return
    elif data == "mama_pending":
        await show_pending_for_mama(update, context)
    elif data == "mama_offers":
        await show_offers_for_mama(update, context)
    elif data == "mama_done":
        await show_done_for_mama(update, context)
    elif data == "mama_add_task":
        user_states[username] = "MAMA_ADD_TASK_TITLE"
        await query.edit_message_text("Введите название задания для добавления:")
    elif data == "mama_delete_task":
        await show_available_tasks_for_deletion(update, context)
    elif data == "mama_stats":
        await show_mama_stats(update, context)
    elif data == "mama_pay":
        user_states[username] = "MAMA_PAY"
        await query.edit_message_text("Введите сумму оплаты Косте:")

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
async def show_pending_for_mama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.callback_query.from_user.username
    pending = [t for t in tasks.values() if t["status"] in [STATUS_SUBMITTED, STATUS_OFFERED]]
    if not pending:
        await update.callback_query.edit_message_text("Нет непроверенных заданий", reply_markup=mama_menu_keyboard())
        return

    text = "Непроверенные задания:\n"
    buttons = []
    for t in pending:
        text += f"{t['id']}. {t['title']} — {t.get('reward_value',0)}\n"
        buttons.append([InlineKeyboardButton(f"{t['id']}", callback_data=f"mama_approve_{t['id']}")])
    buttons.append([InlineKeyboardButton("В главное меню", callback_data="main_menu")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

# ===== ЗАДАНИЯ, СТАТИСТИКА, ОПЛАТА, УДАЛЕНИЕ, ОДОБРЕНИЕ =====
# Здесь нужно добавить функции:
# show_offers_for_mama(), show_done_for_mama(), show_available_tasks_for_deletion(),
# show_mama_stats(), mama_approve_task_handler(), mama_delete_task_handler(),
# mama_pay_handler(), с полной логикой одобрения, расчета коэффициентов, переходов статусов, начислений и ledger.
# Для brevity этот блок оставлен как заготовка, но все кнопки и FSM интегрированы.
# При реализации, каждая функция должна:
# - обновлять task["status"] и использовать update_task(task_id, "status", new_status)
# - добавлять вознаграждения через add_money(username, amount, "TASK_REWARD", comment)
# - учитывать коэффициенты для уровней 2 и 3
# - сохранять серию и математический банк для Кости
# - поддерживать кнопку "В главное меню" на каждом шаге
# ===== ФУНКЦИИ ДЛЯ МЕНЮ МАМЫ: ОДОБРЕНИЕ, ДОБАВЛЕНИЕ, СТАТИСТИКА, УДАЛЕНИЕ, ОПЛАТА =====

# === Показ предложенных Костей заданий для одобрения мамой ===
async def show_offers_for_mama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.callback_query.from_user.username
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

# === Показ выполненных заданий, которые нужно принять ===
async def show_done_for_mama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.callback_query.from_user.username
    done_tasks = [t for t in tasks.values() if t["status"] == STATUS_DONE]
    if not done_tasks:
        await update.callback_query.edit_message_text("Нет выполненных заданий", reply_markup=mama_menu_keyboard())
        return

    text = "Выполненные задания:\n"
    buttons = []
    for t in done_tasks:
        # расчет вознаграждения по уровню и коэффициенту
        reward = t.get("reward_value", 0)
        if t.get("level") == 2:
            reward *= 0.5
        elif t.get("level") == 3:
            reward *= 0.4
        elif t.get("level") == 4:
            score = t.get("score", 0)
            reward = 15 if score <= 20 else 40
        text += f"{t['id']}. {t['title']} — {reward} р.\n"
        buttons.append([InlineKeyboardButton(f"{t['id']}", callback_data=f"mama_accept_{t['id']}")])
    buttons.append([InlineKeyboardButton("В главное меню", callback_data="main_menu")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

# === Добавление задания Мамой (фиксированное) ===
async def mama_add_task_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.from_user.username
    if user_states.get(username) != "MAMA_ADD_TASK_TITLE":
        return
    title = update.message.text.strip()
    task_id = max(tasks.keys(), default=0) + 1
    tasks[task_id] = {
        "id": task_id,
        "title": title,
        "status": STATUS_AVAILABLE,
        "level": 1,
        "reward_value": 1.5,
        "added_by": username
    }
    user_states.pop(username)
    await update.message.reply_text(f"Задание '{title}' добавлено", reply_markup=mama_menu_keyboard())

# === Удаление доступных заданий Мамой ===
async def show_available_tasks_for_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    available = [t for t in tasks.values() if t["status"] == STATUS_AVAILABLE]
    if not available:
        await update.callback_query.edit_message_text("Нет доступных заданий для удаления", reply_markup=mama_menu_keyboard())
        return
    text = "Доступные задания к удалению:\n"
    buttons = []
    for t in available:
        text += f"{t['id']}. {t['title']}\n"
        buttons.append([InlineKeyboardButton(f"Удалить {t['id']}", callback_data=f"mama_delete_{t['id']}")])
    buttons.append([InlineKeyboardButton("В главное меню", callback_data="main_menu")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

async def mama_delete_task_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    task_id = int(query.data.split("_")[-1])
    if task_id in tasks:
        tasks.pop(task_id)
        await query.answer("Задание удалено")
    await show_available_tasks_for_deletion(update, context)

# === Одобрение задания Мамой ===
async def mama_approve_task_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    task_id = int(query.data.split("_")[-1])
    task = tasks.get(task_id)
    if not task:
        await query.answer("Задание не найдено")
        return

    # Одобрение: присвоить статус AVAILABLE
    task["status"] = STATUS_AVAILABLE
    add_money(task["added_by"], task["reward_value"], "TASK_APPROVED", f"Одобрено Мамой {query.from_user.username}")
    await query.answer(f"Задание {task_id} одобрено")
    await show_offers_for_mama(update, context)

# === Оплата Мамой Косте ===
async def mama_pay_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.from_user.username
    if user_states.get(username) != "MAMA_PAY":
        return
    try:
        amount = float(update.message.text.strip())
        add_money("kxstik_smerch", amount, "MAMA_PAY", f"Оплата Мамой {username}")
        add_money("babushka_ira_lub", amount, "MAMA_PAY", f"Оплата Мамой {username}")
        await update.message.reply_text(f"Оплата {amount} р. проведена", reply_markup=mama_menu_keyboard())
    except:
        await update.message.reply_text("Ошибка: введите число", reply_markup=mama_menu_keyboard())
    user_states.pop(username)

# === Статистика Мамы за последние 14 дней ===
async def show_mama_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.callback_query.from_user.username
    # простая демонстрация: суммарные выплаты за 14 дней
    total_earned = sum(l["amount"] for l in ledger if l["date"] >= datetime.now() - timedelta(days=14))
    text = f"Статистика за 14 дней:\nВсего начислено: {total_earned} р."
    await update.callback_query.edit_message_text(text, reply_markup=mama_menu_keyboard())
