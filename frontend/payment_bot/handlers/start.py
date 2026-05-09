#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
/start 和 /help 命令处理
"""

from telegram import Update
from telegram.ext import ContextTypes

from backend.database.session import async_session_maker
from backend.services.user_service import UserService
from frontend.core.i18n import get_user_lang
from frontend.core.utils import tr


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /start 命令：注册/欢迎用户"""
    tg_user = update.effective_user
    telegram_id = tg_user.id

    async with async_session_maker() as session:
        svc = UserService(session)
        user = await svc.get_user(telegram_id)

        if user:
            lang = get_user_lang(user.preferences)
            name = user.display_name
            text = tr("welcome.returning", lang, name=name)
        else:
            user, _ = await svc.get_or_create_user(
                telegram_id,
                telegram_username=tg_user.username,
                first_name=tg_user.first_name,
                last_name=tg_user.last_name,
            )
            lang = get_user_lang(user.preferences)
            text = tr("welcome.greeting", lang) + "\n" + tr("welcome.registered", lang)

    text += "\n\n" + tr("common.help_text", lang)
    await update.message.reply_text(text)


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /help 命令"""
    from frontend.core.utils import get_user_lang_from_update

    lang = await get_user_lang_from_update(update)
    title = tr("common.help_title", lang)
    body = tr("common.help_text", lang)
    await update.message.reply_text(f"{title}\n\n{body}")
