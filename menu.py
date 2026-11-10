"""Меню и контакты кафе: читаются из menu.json, чтобы владелец мог менять их без кода."""

import json
from html import escape
from pathlib import Path

MENU_FILE = Path(__file__).with_name("menu.json")


def load_menu(path: Path = MENU_FILE) -> dict:
    """Прочитать menu.json. Файл читается при каждом вызове — правки видны без перезапуска."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_category(menu: dict, category_id: str) -> dict | None:
    for cat in menu["categories"]:
        if cat["id"] == category_id:
            return cat
    return None


def format_category(category: dict) -> str:
    lines = [f"<b>{escape(category['title'])}</b>", ""]
    for item in category["items"]:
        lines.append(f"• {escape(item['name'])} — {item['price']} ₽")
    return "\n".join(lines)


def format_contacts(menu: dict) -> str:
    cafe = menu["cafe"]
    return (
        f"<b>Кафе «{escape(cafe['name'])}»</b>\n\n"
        f"📍 {escape(cafe['address'])}\n"
        f"📞 {escape(cafe['phone'])}\n"
        f"🕙 {escape(cafe['hours'])}\n"
        f"📷 {escape(cafe['instagram'])}"
    )
