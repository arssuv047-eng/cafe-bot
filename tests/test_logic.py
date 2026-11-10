"""Проверка логики бота без Telegram.

Запуск из папки бота:  python -m unittest -v
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import booking  # noqa: E402
import menu  # noqa: E402
from booking import ValidationError  # noqa: E402

TODAY = date(2026, 12, 20)


class DateTests(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(booking.parse_date("25.12", TODAY), date(2026, 12, 25))
        self.assertEqual(booking.parse_date("25.12.2026", TODAY), date(2026, 12, 25))
        self.assertEqual(booking.parse_date("25/12/26", TODAY), date(2026, 12, 25))
        self.assertEqual(booking.parse_date("Сегодня", TODAY), TODAY)
        self.assertEqual(booking.parse_date("завтра", TODAY), date(2026, 12, 21))

    def test_next_year_rollover(self):
        # 05.01 в декабре — это январь следующего года
        self.assertEqual(booking.parse_date("05.01", TODAY), date(2027, 1, 5))

    def test_invalid(self):
        for bad in ["вчера", "32.12", "31.02", "abc", "19.12.2026", "01.06.2027", ""]:
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                booking.parse_date(bad, TODAY)


class TimeTests(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(booking.parse_time("19:30"), time(19, 30))
        self.assertEqual(booking.parse_time("19.30"), time(19, 30))
        self.assertEqual(booking.parse_time("10"), time(10, 0))
        self.assertEqual(booking.parse_time("21:00"), time(21, 0))  # последний час до закрытия

    def test_outside_hours_or_garbage(self):
        for bad in ["9:59", "21:01", "23:00", "25:00", "19:75", "вечером"]:
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                booking.parse_time(bad)

    def test_past_time_today(self):
        now = datetime(2026, 12, 20, 15, 0)
        with self.assertRaises(ValidationError):
            booking.parse_time("14:00", on_date=now.date(), now=now)
        self.assertEqual(booking.parse_time("16:00", on_date=now.date(), now=now), time(16, 0))
        # На завтра то же время можно
        self.assertEqual(booking.parse_time("14:00", on_date=date(2026, 12, 21), now=now), time(14, 0))


class GuestsAndNameTests(unittest.TestCase):
    def test_guests(self):
        self.assertEqual(booking.parse_guests(" 4 "), 4)
        for bad in ["0", "21", "-1", "два", "2.5"]:
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                booking.parse_guests(bad)

    def test_name(self):
        self.assertEqual(booking.parse_name("  Анна   Иванова "), "Анна Иванова")
        for bad in ["А", "x" * 51, "   "]:
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                booking.parse_name(bad)

    def test_name_is_html_escaped(self):
        b = {"date": "25.12.2026", "time": "19:00", "guests": 2, "name": "<b>Хакер</b>"}
        self.assertIn("&lt;b&gt;", booking.format_summary(b))


class StorageTests(unittest.TestCase):
    def test_save_assigns_ids(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bookings.json"
            b = {"date": "25.12.2026", "time": "19:00", "guests": 2, "name": "Анна", "user_id": 1, "username": None}
            first = booking.save_booking(b, path)
            second = booking.save_booking(b, path)
            self.assertEqual((first["id"], second["id"]), (1, 2))
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0]["name"], "Анна")  # кириллица сохраняется читаемо


class MenuTests(unittest.TestCase):
    def test_menu_json_is_valid(self):
        m = menu.load_menu()
        ids = [c["id"] for c in m["categories"]]
        self.assertEqual(ids, ["coffee", "desserts", "lunch"])
        for c in m["categories"]:
            self.assertTrue(c["items"])
            for item in c["items"]:
                self.assertIsInstance(item["price"], int)
        self.assertIn("Капучино — 240 ₽", menu.format_category(menu.get_category(m, "coffee")))
        self.assertIsNone(menu.get_category(m, "nope"))
        self.assertIn(m["cafe"]["phone"], menu.format_contacts(m))
        # Время работы для брони должно читаться
        time.fromisoformat(m["cafe"]["open_time"])
        time.fromisoformat(m["cafe"]["close_time"])


# ---------- Сценарий брони целиком на поддельных объектах ----------

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("ADMIN_ID", "999")
import bot  # noqa: E402
from config import Config  # noqa: E402


def fake_update(text):
    msg = SimpleNamespace(text=text, reply_text=AsyncMock())
    return SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=42, username="guest"))


def fake_context():
    return SimpleNamespace(
        user_data={},
        bot_data={"config": Config(bot_token="123456:TEST", admin_id=999)},
        bot=SimpleNamespace(send_message=AsyncMock()),
    )


def last_reply(update):
    return update.message.reply_text.call_args.args[0]


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "bookings.json"
        patcher = patch.object(booking, "BOOKINGS_FILE", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def run_step(self, handler, text, ctx):
        upd = fake_update(text)
        state = asyncio.run(handler(upd, ctx))
        return state, upd

    def test_full_booking(self):
        ctx = fake_context()
        state, _ = self.run_step(bot.book_start, bot.BTN_BOOK, ctx)
        self.assertEqual(state, bot.DATE)

        state, upd = self.run_step(bot.book_date, "вчера", ctx)  # ошибка — остаёмся на шаге
        self.assertEqual(state, bot.DATE)
        self.assertIn("⚠️", last_reply(upd))

        state, _ = self.run_step(bot.book_date, "Завтра", ctx)
        self.assertEqual(state, bot.TIME)
        state, _ = self.run_step(bot.book_time, "19:30", ctx)
        self.assertEqual(state, bot.GUESTS)
        state, _ = self.run_step(bot.book_guests, "3", ctx)
        self.assertEqual(state, bot.NAME)
        state, upd = self.run_step(bot.book_name, "Анна", ctx)
        self.assertEqual(state, bot.CONFIRM)
        self.assertIn("Гостей: 3", last_reply(upd))

        state, upd = self.run_step(bot.book_confirm, bot.BTN_CONFIRM, ctx)
        self.assertEqual(state, bot.ConversationHandler.END)
        self.assertIn("Заявка №1 принята", last_reply(upd))

        # Админу ушло сообщение на ID из настроек
        ctx.bot.send_message.assert_awaited_once()
        admin_id, admin_text = ctx.bot.send_message.call_args.args
        self.assertEqual(admin_id, 999)
        self.assertIn("Новая бронь #1", admin_text)
        self.assertIn("@guest", admin_text)

        # И заявка записана в файл
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved[0]["name"], "Анна")
        self.assertEqual(saved[0]["time"], "19:30")
        self.assertEqual(saved[0]["guests"], 3)
        self.assertNotIn("booking", ctx.user_data)

    def test_cancel_midway(self):
        ctx = fake_context()
        self.run_step(bot.book_start, bot.BTN_BOOK, ctx)
        self.run_step(bot.book_date, "завтра", ctx)
        state, upd = self.run_step(bot.book_cancel, bot.BTN_CANCEL, ctx)
        self.assertEqual(state, bot.ConversationHandler.END)
        self.assertIn("отменено", last_reply(upd))
        self.assertNotIn("booking", ctx.user_data)
        self.assertFalse(self.path.exists())
        ctx.bot.send_message.assert_not_awaited()

    def test_admin_unreachable_still_saves(self):
        from telegram.error import Forbidden

        ctx = fake_context()
        ctx.bot.send_message.side_effect = Forbidden("bot can't initiate conversation")
        for handler, text in [
            (bot.book_start, bot.BTN_BOOK),
            (bot.book_date, "завтра"),
            (bot.book_time, "12:00"),
            (bot.book_guests, "2"),
            (bot.book_name, "Иван"),
        ]:
            self.run_step(handler, text, ctx)
        with self.assertLogs("cafe-bot", level="ERROR"):
            _, upd = self.run_step(bot.book_confirm, bot.BTN_CONFIRM, ctx)
        self.assertIn("принята", last_reply(upd))
        self.assertTrue(self.path.exists())

    def test_cancel_filter_matches(self):
        for text in ["❌ Отмена", "отмена", "ОТМЕНА"]:
            self.assertRegex(text, bot.CANCEL_FILTER.pattern)

    def test_network_error_is_short_warning(self):
        from telegram.error import TimedOut

        ctx = SimpleNamespace(error=TimedOut())
        with self.assertLogs("cafe-bot", level="WARNING") as logs:
            asyncio.run(bot.on_error(None, ctx))
        self.assertEqual(logs.records[0].levelname, "WARNING")
        self.assertIsNone(logs.records[0].exc_info)

    def test_app_builds_without_network(self):
        app = bot.build_app(Config(bot_token="123456:TEST", admin_id=999))
        self.assertEqual(len(app.handlers[0]), 8)


if __name__ == "__main__":
    unittest.main()
