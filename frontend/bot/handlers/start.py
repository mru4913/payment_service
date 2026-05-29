#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""/start 和 /help 命令处理。"""

from telegram import Update
from telegram.ext import ContextTypes

from frontend.bot.dashboard_view import (
    account_text_for_user,
    dashboard_text,
    dashboard_text_for_user,
)
from frontend.bot.handlers.history import history_handler
from frontend.bot.handlers.language import lang_handler
from frontend.bot.handlers.task_history import task_history_handler
from frontend.bot.keyboards import (
    dashboard_keyboard,
    home_back_keyboard,
    my_account_keyboard,
)
from frontend.core.i18n import DEFAULT_LANG, get_user_lang, get_user_lang_from_telegram
from frontend.core.utils import get_user_lang_from_update, tr
from frontend.integrations import BackendAPIError, get_backend_client


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /start 命令：经 HTTP 注册用户并展示 Dashboard。"""
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
    await msg.reply_text(
        dashboard_text(
            lang,
            name=name,
            created=created,
        ),
        reply_markup=dashboard_keyboard(lang),
        parse_mode="HTML",
    )


async def dashboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 Dashboard 非流程类按钮。"""
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return

    await query.answer()
    data = query.data or ""
    lang = await get_user_lang_from_update(update)

    if data == "dashboard:home":
        await query.edit_message_text(
            await dashboard_text_for_user(lang, user.id, user.first_name),
            reply_markup=dashboard_keyboard(lang),
            parse_mode="HTML",
        )
        return
    if data == "dashboard:my":
        await query.edit_message_text(
            await account_text_for_user(lang, user.id),
            reply_markup=my_account_keyboard(lang),
            parse_mode="HTML",
        )
        return
    if data == "dashboard:history":
        await history_handler(update, context)
        return
    if data == "dashboard:task_history":
        await task_history_handler(update, context)
        return
    if data == "dashboard:lang":
        await lang_handler(update, context)
        return
    if data == "dashboard:help":
        await query.edit_message_text(
            f"{tr('common.help_title', lang)}\n\n{tr('common.help_text', lang)}",
            reply_markup=home_back_keyboard(lang),
        )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /help 命令"""
    msg = update.effective_message
    if not msg or not update.effective_user:
        return
    lang = await get_user_lang_from_update(update)
    title = tr("common.help_title", lang)
    body = tr("common.help_text", lang)
    await msg.reply_text(f"{title}\n\n{body}")
