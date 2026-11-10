"""Логика бронирования без Telegram: проверка ввода, сводка, сохранение в bookings.json."""

import json
import re
from datetime import date, datetime, time, timedelta
from html import escape
from pathlib import Path

BOOKINGS_FILE = Path(__file__).with_name("bookings.json")

MAX_DAYS_AHEAD = 60
MAX_GUESTS = 20


class ValidationError(ValueError):
    """Пользователь ввёл что-то не то — текст ошибки показываем ему."""


def parse_date(text: str, today: date | None = None) -> date:
    """Принимает «25.12.2026», «25.12» или слова «сегодня» / «завтра»."""
    today = today or date.today()
    text = text.strip().lower()
    if text == "сегодня":
        return today
    if text == "завтра":
        return today + timedelta(days=1)

    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2}|\d{4}))?", text)
    if not m:
        raise ValidationError("Не понял дату. Напишите в формате ДД.ММ, например 25.12.")
    day, month, year = int(m[1]), int(m[2]), m[3]
    if year is None:
        y = today.year
    else:
        y = int(year) + 2000 if len(year) == 2 else int(year)
    try:
        d = date(y, month, day)
    except ValueError:
        raise ValidationError("Такой даты нет. Проверьте день и месяц.") from None
    # «05.01» в декабре — это январь следующего года.
    if year is None and d < today:
        d = date(y + 1, month, day)

    if d < today:
        raise ValidationError("Эта дата уже прошла. Выберите сегодня или позже.")
    if d > today + timedelta(days=MAX_DAYS_AHEAD):
        raise ValidationError(f"Бронируем не дальше чем на {MAX_DAYS_AHEAD} дней вперёд.")
    return d


def parse_time(
    text: str,
    open_time: str = "10:00",
    close_time: str = "22:00",
    on_date: date | None = None,
    now: datetime | None = None,
) -> time:
    """Принимает «19:30», «19.30» или «19». Время должно быть в часы работы,
    не позже чем за час до закрытия и (если бронь на сегодня) ещё не прошедшим."""
    m = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2}))?", text.strip())
    if not m:
        raise ValidationError("Не понял время. Напишите в формате ЧЧ:ММ, например 19:30.")
    hour, minute = int(m[1]), int(m[2] or 0)
    if hour > 23 or minute > 59:
        raise ValidationError("Такого времени нет. Пример: 19:30.")
    t = time(hour, minute)

    opens = time.fromisoformat(open_time)
    last = (datetime.combine(date.today(), time.fromisoformat(close_time)) - timedelta(hours=1)).time()
    if not (opens <= t <= last):
        raise ValidationError(
            f"Мы принимаем брони с {opens:%H:%M} до {last:%H:%M} (за час до закрытия)."
        )
    now = now or datetime.now()
    if on_date is not None and on_date == now.date() and t <= now.time():
        raise ValidationError("Это время сегодня уже прошло. Выберите время позже.")
    return t


def parse_guests(text: str) -> int:
    text = text.strip()
    if not text.isdigit():
        raise ValidationError("Напишите количество гостей числом, например 2.")
    n = int(text)
    if not 1 <= n <= MAX_GUESTS:
        raise ValidationError(f"Можно забронировать от 1 до {MAX_GUESTS} гостей. Для банкета позвоните нам.")
    return n


def parse_name(text: str) -> str:
    name = " ".join(text.split())
    if not 2 <= len(name) <= 50:
        raise ValidationError("Имя должно быть от 2 до 50 символов.")
    return name


def format_summary(b: dict) -> str:
    return (
        f"📅 Дата: {b['date']}\n"
        f"🕖 Время: {b['time']}\n"
        f"👥 Гостей: {b['guests']}\n"
        f"🙂 Имя: {escape(b['name'])}"
    )


def format_admin_message(b: dict) -> str:
    username = f"@{escape(b['username'])}" if b.get("username") else "нет username"
    return (
        f"🔔 <b>Новая бронь #{b['id']}</b>\n\n"
        f"{format_summary(b)}\n\n"
        f"Telegram: {username} (ID <code>{b['user_id']}</code>)"
    )


def load_bookings(path: Path | None = None) -> list[dict]:
    path = path or BOOKINGS_FILE
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_booking(booking: dict, path: Path | None = None) -> dict:
    """Добавить заявку в файл, присвоить ей номер и время создания. Возвращает сохранённую заявку."""
    path = path or BOOKINGS_FILE
    bookings = load_bookings(path)
    saved = {
        "id": max((b["id"] for b in bookings), default=0) + 1,
        **booking,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    bookings.append(saved)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(bookings, f, ensure_ascii=False, indent=2)
    tmp.replace(path)  # запись через временный файл — чтобы не испортить данные при сбое
    return saved
