#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
/lang 语言切换
"""

from telegram import Update
from telegram.ext import ContextTypes

from backend.database.session import async_session_maker
from backend.services.user_service import UserService
from frontend.core.i18n import get_user_lang, lang_display_name, SUPPORTED_LANGS
from frontend.core.utils import tr
from frontend.payment_bot.keyboards import language_keyboard


async def lang_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /lang 命令：展示语言选择键盘"""
    telegram_id = update.effective_user.id
    async with async_session_maker() as session:
        svc = UserService(session)
        user = await svc.get_user(telegram_id)
    lang = get_user_lang(user.preferences if user else None)

    await update.message.reply_text(
        tr("language.select", lang), reply_markup=language_keyboard()
    )


async def lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理语言选择回调 lang:<code>"""
    query = update.callback_query
    await query.answer()

    new_lang = query.data.split(":")[-1]
    if new_lang not in SUPPORTED_LANGS:
        return

    telegram_id = update.effective_user.id

    async with async_session_maker() as session:
        svc = UserService(session)
        user = await svc.get_user(telegram_id)
        if user:
            prefs = user.preferences or {}
            prefs["lang"] = new_lang
            await svc.update_user(telegram_id, preferences=prefs)

    display = lang_display_name(new_lang)
    await query.edit_message_text(tr("language.changed", new_lang, lang=display))
