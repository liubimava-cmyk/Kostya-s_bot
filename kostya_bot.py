import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler

# Настройка логов
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Токен бота
TOKEN = "8689635759:AAGEAzQV4dqzGBxoaekkX0Esv5-OpcXOq5g"

# Никнеймы
KOSTYA = "@kxstik_smerch"
MAMA = "@Lbimova"

# Задания
tasks = [
    {"group": 1, "text": "Помыть посуду", "bonus": "1.5 р."},
    {"group": 1, "text": "Протереть стол", "bonus": "1.5 р."},
    {"group": 1, "text": "Уборка зоны комнаты", "bonus": "1.5 р."},
    {"group": 1, "text": "Выбросить мусор", "bonus": "1.5 р."},
    {"group": 1, "text": "Вовремя пришёл в школу", "bonus": "5 р."},
    {"group": 1, "text": "Лоток кота", "bonus": "1.5 р."},
    {"group": 1, "text": "Не ночью в магазин / прогулка", "bonus": "1.5 р."},
    {"group": 2, "text": "Русский ЦТ", "bonus": "коэф. 0.5"},
    {"group": 2, "text": "Английский ЦТ", "bonus": "коэф. 0.5"},
    {"group": 3, "text": "Математика ЦТ до 20 баллов", "bonus": "15 р."},
    {"group": 3, "text": "Математика ЦТ выше 20 баллов", "bonus": "40 р."},
]

# Список результатов, ожидающих одобрения
pending = []

# Хранилище принятых заданий
approved = []

# Команды для кнопок
keyboard = [
    [InlineKeyboardButton("/help", callback_data='help')],
    [InlineKeyboardButton("/tasks", callback_data='tasks')],
    [InlineKeyboardButton("/done", callback_data='done')],
]

markup = InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username
    msg = ("Привет! Вот список доступных заданий:\n"
           "*не просто любое задание, Костя - ПРОЧИТАЙ ПРАВИЛА по команде /help\n\n")
    for idx, t in enumerate(tasks, 1):
        msg += f"{idx}. {t['text']} ({t['bonus']})\n"
    await update.message.reply_text(msg, reply_markup=markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "Правила:\n"
        "- Каждый день выбираешь любое задание из списка (1–2 максимум)\n"
        "- Пропуск = полный сброс бонуса\n"
        "- Бонус за 3 дня подряд: 15 р.\n"
        "- Бонус за 7 дней подряд: 25 р.\n"
        "- Нельзя более 2 дней подряд делать только задания 1 или 2 группы\n"
        "- Хорошая оценка в школе (>6) = зачёт одного задания из 1 или 2 группы\n"
        "- Плохая оценка = отработка правила по русскому, или 3 ЦТ рус., или 1 ЦТ матем.\n"
        "- ЦТ по математике: до 20 баллов = 15 р., выше 20 баллов = 40 р.\n"
        "- Система оценки может быть подкорректирована после реальных результатов\n"
    )
    await update.message.reply_text(msg)

async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "Список заданий:\n"
    for idx, t in enumerate(tasks, 1):
        msg += f"{idx}. {t['text']} ({t['bonus']})\n"
    await update.message.reply_text(msg, reply_markup=markup)

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username
    if user != KOSTYA:
        await update.message.reply_text("Спасибо за работу, но вы не Костя.")
        return
    if len(context.args) == 0:
        await update.message.reply_text("Используй /done <номер задания>")
        return
    try:
        num = int(context.args[0])
        if num < 1 or num > len(tasks):
            await update.message.reply_text("Неверный номер задания")
            return
        task = tasks[num - 1]
        pending.append({"user": user, "task": task})
        await update.message.reply_text(f"Задание '{task['text']}' отправлено на проверку маме.")
    except ValueError:
        await update.message.reply_text("Неверный номер задания")

async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username
    if user != MAMA:
        await update.message.reply_text("У вас нет прав на одобрение.")
        return
    if not pending:
        await update.message.reply_text("Нет заданий на одобрение.")
        return
    msg = "Задания на одобрение:\n"
    for idx, t in enumerate(pending, 1):
        task = t['task']
        msg += f"{idx}. {task['text']} ({task['bonus']})\n"
    await update.message.reply_text(msg)
    # Одобряем все
    approved.extend(pending.copy())
    pending.clear()
    await update.message.reply_text("Все задания одобрены и добавлены в статистику.")

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "help":
        await help_command(update, context)
    elif query.data == "tasks":
        await tasks_command(update, context)
    elif query.data == "done":
        await query.message.reply_text("Используй команду /done <номер задания>")

async def add_task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username
    if user != MAMA:
        await update.message.reply_text("У вас нет прав на добавление заданий.")
        return
    if len(context.args) < 3:
        await update.message.reply_text("Используй /addtask <группа> <текст> <вознаграждение>")
        return
    try:
        group = int(context.args[0])
        text = context.args[1]
        bonus = context.args[2]
        tasks.append({"group": group, "text": text, "bonus": bonus})
        await update.message.reply_text(f"Задание '{text}' добавлено в группу {group} с бонусом {bonus}.")
    except ValueError:
        await update.message.reply_text("Ошибка при добавлении задания.")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("tasks", tasks_command))
    app.add_handler(CommandHandler("done", done_command))
    app.add_handler(CommandHandler("approve", approve_command))
    app.add_handler(CommandHandler("addtask", add_task_command))
    app.add_handler(CallbackQueryHandler(button))
    app.run_polling()

if __name__ == "__main__":
    main()
