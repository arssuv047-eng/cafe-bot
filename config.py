"""Настройки из .env. Секретов в коде нет."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    """Не хватает или неверна настройка в .env."""


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_id: int


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    admin = os.getenv("ADMIN_ID", "").strip()
    if not token:
        raise ConfigError("BOT_TOKEN не задан. Скопируйте .env.example в .env и заполните его.")
    if not admin.lstrip("-").isdigit():
        raise ConfigError("ADMIN_ID должен быть числом (ваш Telegram ID, узнать: @userinfobot).")
    return Config(bot_token=token, admin_id=int(admin))
