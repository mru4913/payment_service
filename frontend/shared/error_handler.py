#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
全局错误处理
"""

from telegram import Update
from telegram.ext import ContextTypes

from backend.globals import logger


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Bot 全局异常处理器"""
    logger.error(f"Bot 异常: {context.error}", exc_info=context.error)

    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("❌ 系统异常，请稍后重试。")
        except Exception:
            pass
