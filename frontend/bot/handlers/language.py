#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
/lang 语言切换
"""

from telegram import Update
from telegram.ext import ContextTypes

from frontend.core.i18n import get_user_lang, lang_display_name, SUPPORTED_LANGS
from frontend.core.utils import tr
from frontend.bot.keyboards import language_keyboard
from frontend.integrations import BackendAPIError, get_backend_client


async def lang_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /lang 命令：展示语言选择键盘"""
    msg = update.effective_message
    if not msg or not update.effective_user:
        return
    telegram_id = update.effective_user.id
    client = get_backend_client()
    prefs = None
    try:
        user = await client.get_user(telegram_id)
        prefs = user.get("preferences")
    except BackendAPIError as e:
        if (
            e.http_status not in (404,)
            and not e.is_transport
            and e.http_status not in (401, 403)
        ):
            await msg.reply_text(tr("common.error", "zh_hans"))
            return

    lang = get_user_lang(prefs)
    await msg.reply_text(tr("language.select", lang), reply_markup=language_keyboard())


async def lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理语言选择回调 lang:<code>"""
    query = update.callback_query
    await query.answer()

    new_lang = query.data.split(":")[-1]
    if new_lang not in SUPPORTED_LANGS:
        return

    telegram_id = update.effective_user.id
    client = get_backend_client()
    try:
        try:
            user = await client.get_user(telegram_id)
            base = dict(user.get("preferences") or {})
        except BackendAPIError as e:
            if e.http_status == 404:
                await client.ensure_user(
                    telegram_id,
                    telegram_username=update.effective_user.username,
                    first_name=update.effective_user.first_name,
                    last_name=update.effective_user.last_name,
                )
                base = {}
            else:
                raise
        base["lang"] = new_lang
        await client.patch_user(telegram_id, {"preferences": base})
    except BackendAPIError:
        await query.edit_message_text(tr("common.error", new_lang))
        return

    display = lang_display_name(new_lang)
    await query.edit_message_text(tr("language.changed", new_lang, lang=display))
