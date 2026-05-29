#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
全局错误处理
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from frontend.core.i18n import get_user_lang_from_telegram, t

logger = logging.getLogger("frontend.error_handler")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Bot 全局异常处理器"""
    logger.error("Bot 异常: %s", context.error, exc_info=context.error)

    if isinstance(update, Update) and update.effective_message:
        try:
            lang = get_user_lang_from_telegram(update.effective_user)
            await update.effective_message.reply_text(t("errors.unhandled", lang=lang))
        except Exception:
            pass
