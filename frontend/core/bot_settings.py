# -*- coding: utf-8 -*-
"""Telegram Bot 进程自身配置（不读 DATABASE_URL，不 import backend.config）。"""

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    """与 HTTP 后端解耦；仅 Bot 运行时需要的变量。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: Optional[str] = None


def load_bot_settings() -> BotSettings:
    return BotSettings()
