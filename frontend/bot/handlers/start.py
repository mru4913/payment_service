#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
/start 和 /help 命令处理
"""

from telegram import Update
from telegram.ext import ContextTypes

from frontend.core.i18n import DEFAULT_LANG, get_user_lang, get_user_lang_from_telegram
from frontend.core.utils import get_user_lang_from_update, tr
from frontend.integrations import BackendAPIError, get_backend_client


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /start 命令：经 HTTP 注册/欢迎用户。"""
    msg = update.effective_message
    tg_user = update.effective_user
    if not msg or not tg_user:
        return

    telegram_id = tg_user.id
    client = get_backend_client()
    err_lang = get_user_lang_from_telegram(tg_user) or DEFAULT_LANG

    try:
        post = await client.ensure_user(
            telegram_id,
            telegram_username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
        )
        created = bool(post.get("created"))
        await client.patch_user(
            telegram_id,
            {
                "telegram_username": tg_user.username,
                "first_name": tg_user.first_name,
                "last_name": tg_user.last_name,
            },
        )
        user = await client.get_user(telegram_id)
    except BackendAPIError:
        await msg.reply_text(tr("common.error", err_lang))
        return

    lang = get_user_lang(user.get("preferences"))
    name = user.get("display_name") or (tg_user.first_name or str(telegram_id))
    if created:
        text = tr("welcome.greeting", lang) + "\n" + tr("welcome.registered", lang)
    else:
        text = tr("welcome.returning", lang, name=name)

    text += "\n\n" + tr("common.help_text", lang)
    await msg.reply_text(text)


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /help 命令"""
    msg = update.effective_message
    if not msg or not update.effective_user:
        return
    lang = await get_user_lang_from_update(update)
    title = tr("common.help_title", lang)
    body = tr("common.help_text", lang)
    await msg.reply_text(f"{title}\n\n{body}")
