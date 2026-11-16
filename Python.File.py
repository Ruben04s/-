import json
import logging
import os
from datetime import date

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ---------------------------------------------------------------- настройки
TOKEN = os.getenv("BOT_TOKEN", "8912765654:AAEMsY-SuV-AoUPtTENQwhrju0i7Ed2dPsA")
DAILY_NORM_ML = 2000          # рекомендованная норма: 2 литра
DATA_FILE = "data.json"       # здесь хранятся данные пользователей

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# ------------------------------------------------------------ хранение данных
# Структура: {"chat_id": {"interval": 2 или None, "drank": 300, "date": "2026-11-16"}}
users = {}


def load_data() -> None:
    """Загружает данные из файла при запуске бота."""
    global users
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)


def save_data() -> None:
    """Сохраняет данные в файл."""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def get_user(chat_id: int) -> dict:
    """Возвращает данные пользователя; если наступил новый день - обнуляет счётчик воды."""
    key = str(chat_id)
    today = date.today().isoformat()
    if key not in users:
        users[key] = {"interval": None, "drank": 0, "date": today}
    if users[key]["date"] != today:
        users[key]["drank"] = 0
        users[key]["date"] = today
    return users[key]


def remaining_ml(user: dict) -> int:
    return max(0, DAILY_NORM_ML - user["drank"])


# ------------------------------------------------------------- напоминания
async def send_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Вызывается по расписанию: отправляет напоминание пользователю."""
    chat_id = context.job.chat_id
    user = get_user(chat_id)
    text = "💧 Не забывай пить воду! Выпей стакан воды."
    left = remaining_ml(user)
    if left > 0:
        text += f"\nДо нормы осталось выпить: {left} мл."
    else:
        text += "\nНорма на сегодня уже выполнена, молодец! 🎉"
    await context.bot.send_message(chat_id=chat_id, text=text)


def remove_jobs(application: Application, chat_id: int) -> None:
    """Удаляет старые напоминания пользователя (чтобы они не дублировались)."""
    for job in application.job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()


def schedule_reminder(application: Application, chat_id: int, hours: float) -> None:
    """Создаёт повторяющееся напоминание каждые `hours` часов."""
    remove_jobs(application, chat_id)
    seconds = int(hours * 3600)
    application.job_queue.run_repeating(
        send_reminder,
        interval=seconds,
        first=seconds,
        chat_id=chat_id,
        name=str(chat_id),
    )


# ------------------------------------------------------------------ команды
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    get_user(update.effective_chat.id)
    save_data()
    await update.message.reply_text(
        "Привет! 👋 Я помогу тебе не забывать пить воду.\n\n"
        "Мои команды:\n"
        "/setreminder N - напоминать каждые N часов (например, /setreminder 2)\n"
        "/stopreminder - отключить напоминания\n"
        "/drank X - записать выпитую воду в мл (например, /drank 300)\n"
        "/status - узнать, сколько ещё нужно выпить\n\n"
        f"Дневная норма: {DAILY_NORM_ML} мл."
    )


async def set_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Укажи число часов, например: /setreminder 1")
        return
    try:
        hours = float(context.args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text("Нужно число, например: /setreminder 2")
        return
    if not 0.5 <= hours <= 24:
        await update.message.reply_text("Интервал должен быть от 0.5 до 24 часов.")
        return

    user = get_user(chat_id)
    user["interval"] = hours
    save_data()
    schedule_reminder(context.application, chat_id, hours)
    await update.message.reply_text(f"✅ Готово! Буду напоминать пить воду каждые {hours:g} ч.")


async def stop_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    remove_jobs(context.application, chat_id)
    get_user(chat_id)["interval"] = None
    save_data()
    await update.message.reply_text("🔕 Напоминания отключены.")


async def drank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Укажи количество в мл, например: /drank 300")
        return
    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Нужно целое число, например: /drank 300")
        return
    if not 0 < amount <= 3000:
        await update.message.reply_text("Введи значение от 1 до 3000 мл за один раз.")
        return

    user = get_user(chat_id)
    user["drank"] += amount
    save_data()

    left = remaining_ml(user)
    if left > 0:
        await update.message.reply_text(
            f"👍 Записано: {amount} мл.\nВсего за сегодня: {user['drank']} мл. "
            f"Осталось: {left} мл."
        )
    else:
        await update.message.reply_text(
            f"🎉 Записано: {amount} мл.\nВсего за сегодня: {user['drank']} мл. "
            "Дневная норма выполнена!"
        )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user(update.effective_chat.id)
    left = remaining_ml(user)
    percent = min(100, round(user["drank"] / DAILY_NORM_ML * 100))
    interval = f"каждые {user['interval']:g} ч." if user["interval"] else "выключены"

    text = (
        f"📊 Статус на сегодня:\n"
        f"Выпито: {user['drank']} мл из {DAILY_NORM_ML} мл ({percent}%)\n"
        f"Напоминания: {interval}\n"
    )
    text += f"Осталось выпить: {left} мл." if left > 0 else "Норма выполнена! 🎉"
    await update.message.reply_text(text)


# ---------------------------------------------------------------- запуск
async def restore_jobs(application: Application) -> None:
    """При перезапуске бота восстанавливает напоминания из файла."""
    for chat_id, user in users.items():
        if user.get("interval"):
            schedule_reminder(application, int(chat_id), user["interval"])


def main() -> None:
    load_data()
    app = Application.builder().token(TOKEN).post_init(restore_jobs).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setreminder", set_reminder))
    app.add_handler(CommandHandler("stopreminder", stop_reminder))
    app.add_handler(CommandHandler("drank", drank))
    app.add_handler(CommandHandler("status", status))

    print("Бот запущен. Для остановки нажмите Ctrl+C.")
    app.run_polling()


if __name__ == "__main__":
    main()