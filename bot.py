"""Telegram-бот кафе «Уют»: меню, контакты и бронирование столиков."""

import logging

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import booking
from config import Config, load_config
from menu import format_category, format_contacts, get_category, load_menu

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
# httpx пишет в лог URL запросов, а в них есть токен — приглушаем.
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("cafe-bot")

# Тексты кнопок
BTN_MENU = "📋 Меню"
BTN_BOOK = "📅 Забронировать столик"
BTN_CONTACTS = "📞 Контакты"
BTN_CANCEL = "❌ Отмена"
BTN_CONFIRM = "✅ Подтвердить"
BTN_TODAY = "Сегодня"
BTN_TOMORROW = "Завтра"

MAIN_KB = ReplyKeyboardMarkup([[BTN_MENU, BTN_BOOK], [BTN_CONTACTS]], resize_keyboard=True)
CANCEL_KB = ReplyKeyboardMarkup([[BTN_CANCEL]], resize_keyboard=True)
DATE_KB = ReplyKeyboardMarkup([[BTN_TODAY, BTN_TOMORROW], [BTN_CANCEL]], resize_keyboard=True)
GUESTS_KB = ReplyKeyboardMarkup([["1", "2", "3", "4"], ["5", "6", "7", "8"], [BTN_CANCEL]], resize_keyboard=True)
CONFIRM_KB = ReplyKeyboardMarkup([[BTN_CONFIRM], [BTN_CANCEL]], resize_keyboard=True)

# Шаги бронирования
DATE, TIME, GUESTS, NAME, CONFIRM = range(5)

HELP_TEXT = (
    "<b>Что умеет бот</b>\n\n"
    f"{BTN_MENU} — меню кафе по категориям с ценами\n"
    f"{BTN_BOOK} — бронь столика за 4 шага\n"
    f"{BTN_CONTACTS} — адрес, телефон, часы работы\n\n"
    "<b>Команды</b>\n"
    "/start — главное меню\n"
    "/book — забронировать столик\n"
    "/cancel — отменить бронирование\n"
    "/help — эта справка\n\n"
    f"На любом шаге брони можно нажать «{BTN_CANCEL}»."
)

# Принимаем и кнопку, и просто слово «отмена» в любом регистре.
CANCEL_FILTER = filters.Regex(r"(?i)^(❌\s*)?отмена$")
TEXT_INPUT = filters.TEXT & ~filters.COMMAND & ~CANCEL_FILTER


def exact(text: str) -> filters.MessageFilter:
    return filters.Text([text])


# ---------- Общие команды ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("booking", None)
    name = load_menu()["cafe"]["name"]
    await update.message.reply_text(
        f"Здравствуйте! 👋 Это бот кафе «{name}».\n\n"
        "Здесь можно посмотреть меню, узнать контакты и забронировать столик. "
        "Выберите, что нужно, кнопками ниже.",
        reply_markup=MAIN_KB,
    )
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Возвращаем None — если пользователь в середине брони, шаг не сбрасывается.
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)


async def contacts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(format_contacts(load_menu()), parse_mode=ParseMode.HTML)


async def cancel_outside(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Сейчас нечего отменять 🙂", reply_markup=MAIN_KB)


# ---------- Меню ----------

def categories_kb(menu: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(c["title"], callback_data=f"cat:{c['id']}")] for c in menu["categories"]]
    )


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Выберите категорию:", reply_markup=categories_kb(load_menu()))


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    menu = load_menu()

    if query.data == "cats":
        await query.edit_message_text("Выберите категорию:", reply_markup=categories_kb(menu))
        return

    category = get_category(menu, query.data.removeprefix("cat:"))
    if category is None:  # категорию удалили из menu.json, а старая кнопка осталась
        await query.edit_message_text("Этой категории больше нет.", reply_markup=categories_kb(menu))
        return
    back = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Все категории", callback_data="cats")]])
    await query.edit_message_text(format_category(category), parse_mode=ParseMode.HTML, reply_markup=back)


# ---------- Бронирование ----------

async def book_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["booking"] = {}
    await update.message.reply_text(
        "Забронируем столик! Шаг 1 из 4.\n\n"
        "📅 На какую дату? Напишите в формате ДД.ММ (например, 25.12) или нажмите кнопку.",
        reply_markup=DATE_KB,
    )
    return DATE


async def book_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        d = booking.parse_date(update.message.text)
    except booking.ValidationError as e:
        await update.message.reply_text(f"⚠️ {e}", reply_markup=DATE_KB)
        return DATE

    context.user_data["booking"]["date"] = d
    cafe = load_menu()["cafe"]
    await update.message.reply_text(
        f"Шаг 2 из 4.\n\n🕖 Во сколько? Напишите время, например 19:30.\n"
        f"Мы работаем с {cafe['open_time']} до {cafe['close_time']}.",
        reply_markup=CANCEL_KB,
    )
    return TIME


async def book_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cafe = load_menu()["cafe"]
    try:
        t = booking.parse_time(
            update.message.text,
            open_time=cafe["open_time"],
            close_time=cafe["close_time"],
            on_date=context.user_data["booking"]["date"],
        )
    except booking.ValidationError as e:
        await update.message.reply_text(f"⚠️ {e}", reply_markup=CANCEL_KB)
        return TIME

    context.user_data["booking"]["time"] = t
    await update.message.reply_text(
        "Шаг 3 из 4.\n\n👥 Сколько будет гостей? Нажмите кнопку или напишите число.",
        reply_markup=GUESTS_KB,
    )
    return GUESTS


async def book_guests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        n = booking.parse_guests(update.message.text)
    except booking.ValidationError as e:
        await update.message.reply_text(f"⚠️ {e}", reply_markup=GUESTS_KB)
        return GUESTS

    context.user_data["booking"]["guests"] = n
    await update.message.reply_text("Шаг 4 из 4.\n\n🙂 На чьё имя бронируем?", reply_markup=CANCEL_KB)
    return NAME


def booking_record(data: dict, update: Update) -> dict:
    """Собрать заявку в виде, пригодном для JSON и показа."""
    user = update.effective_user
    return {
        "date": data["date"].strftime("%d.%m.%Y"),
        "time": data["time"].strftime("%H:%M"),
        "guests": data["guests"],
        "name": data["name"],
        "user_id": user.id,
        "username": user.username,
    }


async def book_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        name = booking.parse_name(update.message.text)
    except booking.ValidationError as e:
        await update.message.reply_text(f"⚠️ {e}", reply_markup=CANCEL_KB)
        return NAME

    context.user_data["booking"]["name"] = name
    summary = booking.format_summary(booking_record(context.user_data["booking"], update))
    await update.message.reply_text(
        f"Проверьте, всё ли верно:\n\n{summary}\n\nЕсли да — нажмите «{BTN_CONFIRM}».",
        parse_mode=ParseMode.HTML,
        reply_markup=CONFIRM_KB,
    )
    return CONFIRM


async def book_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    config: Config = context.bot_data["config"]
    saved = booking.save_booking(booking_record(context.user_data.pop("booking"), update))
    log.info("Бронь #%s сохранена", saved["id"])

    try:
        await context.bot.send_message(
            config.admin_id, booking.format_admin_message(saved), parse_mode=ParseMode.HTML
        )
    except TelegramError:
        # Заявка уже в bookings.json, так что не теряется. Частая причина: админ не нажал /start у бота.
        log.exception("Не удалось отправить бронь #%s администратору", saved["id"])

    await update.message.reply_text(
        f"🎉 Заявка №{saved['id']} принята!\n\n{booking.format_summary(saved)}\n\n"
        "Администратор свяжется с вами, если что-то нужно уточнить. Ждём вас!",
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_KB,
    )
    return ConversationHandler.END


async def book_confirm_other(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        f"Нажмите «{BTN_CONFIRM}», чтобы отправить заявку, или «{BTN_CANCEL}».",
        reply_markup=CONFIRM_KB,
    )
    return CONFIRM


async def book_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("booking", None)
    await update.message.reply_text("Бронирование отменено. Чем ещё помочь?", reply_markup=MAIN_KB)
    return ConversationHandler.END


# ---------- Сборка приложения ----------

def build_app(config: Config) -> Application:
    app = Application.builder().token(config.bot_token).build()
    app.bot_data["config"] = config

    booking_conv = ConversationHandler(
        entry_points=[
            CommandHandler("book", book_start),
            MessageHandler(exact(BTN_BOOK), book_start),
        ],
        states={
            DATE: [MessageHandler(TEXT_INPUT, book_date)],
            TIME: [MessageHandler(TEXT_INPUT, book_time)],
            GUESTS: [MessageHandler(TEXT_INPUT, book_guests)],
            NAME: [MessageHandler(TEXT_INPUT, book_name)],
            CONFIRM: [
                MessageHandler(exact(BTN_CONFIRM), book_confirm),
                MessageHandler(TEXT_INPUT, book_confirm_other),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", book_cancel),
            MessageHandler(CANCEL_FILTER, book_cancel),
            CommandHandler("start", start),
            CommandHandler("help", help_command),
        ],
    )

    app.add_handler(booking_conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel_outside))
    app.add_handler(MessageHandler(CANCEL_FILTER, cancel_outside))
    app.add_handler(MessageHandler(exact(BTN_MENU), show_menu))
    app.add_handler(MessageHandler(exact(BTN_CONTACTS), contacts))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^(cat:|cats$)"))
    return app


def main() -> None:
    config = load_config()
    app = build_app(config)
    log.info("Бот кафе запущен. Остановка: Ctrl+C")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
