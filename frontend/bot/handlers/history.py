#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
/history 交易记录查询（分页，经 HTTP）
"""

import math
from decimal import Decimal

from telegram import Update
from telegram.ext import ContextTypes

from frontend.core.utils import (
    get_user_lang_from_update,
    tr,
    format_amount,
    format_datetime,
)
from frontend.bot.keyboards import pagination_keyboard
from frontend.integrations import BackendAPIError, get_backend_client

PER_PAGE = 5

_TYPE_ICONS = {
    "deposit": "📥",
    "withdraw": "📤",
    "refund": "🔄",
    "payment": "💳",
    "hold": "🔒",
    "hold_release": "🔓",
    "consumption": "⚡",
}


async def history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /history 命令"""
    await _show_history(update, page=1, edit=bool(update.callback_query))


async def history_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理分页翻页回调 history_page:<n>"""
    query = update.callback_query
    await query.answer()
    try:
        page = int(query.data.split(":")[-1])
    except (ValueError, IndexError):
        page = 1
    await _show_history(update, page=page, edit=True)


async def _show_history(update: Update, page: int = 1, edit: bool = False):
    if not update.effective_user:
        return
    lang = await get_user_lang_from_update(update)
    telegram_id = update.effective_user.id
    client = get_backend_client()

    skip = max(0, (page - 1) * PER_PAGE)
    try:
        data = await client.list_user_transactions(
            telegram_id, skip=skip, limit=PER_PAGE
        )
    except BackendAPIError as e:
        if e.is_transport:
            msg = tr("errors.backend_transport", lang)
        elif e.http_status in (401, 403):
            msg = tr("errors.backend_auth", lang)
        else:
            msg = tr("common.error", lang)
        if edit and update.callback_query:
            await update.callback_query.edit_message_text(msg)
        elif update.effective_message:
            await update.effective_message.reply_text(msg)
        return

    total = int(data.get("total") or 0)
    page_txs = list(data.get("transactions") or [])
    if total == 0:
        text = tr("history.title", lang) + "\n\n" + tr("history.empty", lang)
        keyboard = pagination_keyboard(
            1,
            1,
            "history_page",
            lang,
            back_callback="dashboard:my" if edit else None,
        )
        if edit and update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=keyboard)
        elif update.effective_message:
            await update.effective_message.reply_text(text, reply_markup=keyboard)
        return

    total_pages = max(1, math.ceil(total / PER_PAGE))
    display_page = max(1, min(page, total_pages))
    if display_page != page:
        skip = (display_page - 1) * PER_PAGE
        data = await client.list_user_transactions(
            telegram_id, skip=skip, limit=PER_PAGE
        )
        page_txs = list(data.get("transactions") or [])

    lines = [tr("history.title", lang), ""]
    for tx in page_txs:
        t_type = tx.get("transaction_type", "")
        icon = _TYPE_ICONS.get(t_type, "📋")
        type_key = f"history.type_{t_type}"
        type_name = tr(type_key, lang)
        if type_name == type_key:
            type_name = str(t_type)

        amt = Decimal(str(tx.get("amount_usd", "0")))
        lines.append(
            tr(
                "history.entry",
                lang,
                icon=icon,
                type_name=type_name,
                amount=format_amount(amt),
                time=format_datetime(tx.get("created_at")),
            )
        )

    lines.append("")
    lines.append(tr("history.page", lang, current=display_page, total=total_pages))

    text = "\n".join(lines)
    keyboard = pagination_keyboard(
        display_page,
        total_pages,
        "history_page",
        lang,
        back_callback="dashboard:my" if edit else None,
    )

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard)
    elif update.effective_message:
        await update.effective_message.reply_text(text, reply_markup=keyboard)
