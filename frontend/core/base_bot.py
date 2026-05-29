#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Bot 基类 - 提供初始化、日志和通用上下文工具
"""

import logging

from telegram import BotCommand
from telegram.ext import Application

from frontend.core.bot_settings import load_bot_settings
from frontend.core.i18n import t

logger = logging.getLogger("frontend.bot")

PUBLIC_BOT_COMMAND_KEYS: tuple[tuple[str, str], ...] = (
    ("start", "bot_commands.start"),
    ("help", "bot_commands.help"),
)
TELEGRAM_COMMAND_LANGS: tuple[tuple[str, str], ...] = (
    ("zh", "zh_hans"),
    ("en", "en"),
)


async def sync_bot_commands(app: Application) -> None:
    """Publish only the user-facing command menu.

    Product workflows are intentionally entered from the Dashboard UI, so old
    command-menu entries such as /compute are removed when the bot starts.
    """
    try:
        default_commands = [
            BotCommand(command, description)
            for command, description in _localized_commands("en")
        ]
        await app.bot.set_my_commands(default_commands)
        for telegram_lang, app_lang in TELEGRAM_COMMAND_LANGS:
            await app.bot.set_my_commands(
                [
                    BotCommand(command, description)
                    for command, description in _localized_commands(app_lang)
                ],
                language_code=telegram_lang,
            )
    except Exception:
        logger.warning("Telegram Bot command menu sync failed", exc_info=True)
        return
    logger.info(
        "Telegram Bot command menu synced commands=%s langs=%s",
        ",".join(command for command, _ in PUBLIC_BOT_COMMAND_KEYS),
        ",".join(lang for lang, _ in TELEGRAM_COMMAND_LANGS),
    )


def _localized_commands(lang: str) -> tuple[tuple[str, str], ...]:
    return tuple(
        (command, t(key, lang=lang))
        for command, key in PUBLIC_BOT_COMMAND_KEYS
    )


def create_bot_application() -> Application:
    """创建并配置 Bot Application 实例。"""
    settings = load_bot_settings()
    token = settings.telegram_bot_token
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 未配置")

    app = Application.builder().token(token).post_init(sync_bot_commands).build()
    logger.info("Telegram Bot Application 已创建")
    return app
