#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Bot 基类 - 提供初始化、日志和通用上下文工具
"""

import logging

from telegram.ext import Application

from frontend.core.bot_settings import load_bot_settings

logger = logging.getLogger("frontend.bot")


def create_bot_application() -> Application:
    """创建并配置 Bot Application 实例。"""
    settings = load_bot_settings()
    token = settings.telegram_bot_token
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 未配置")

    app = Application.builder().token(token).build()
    logger.info("Telegram Bot Application 已创建")
    return app
