#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
/history 交易记录查询（分页）
"""

from telegram import Update
from telegram.ext import ContextTypes

from backend.database.session import async_session_maker
from backend.services.balance_service import BalanceService
from frontend.core.utils import (
    get_user_lang_from_update,
    tr,
    format_amount,
    format_datetime,
    paginate,
)
from frontend.payment_bot.keyboards import pagination_keyboard

PER_PAGE = 5

_TYPE_ICONS = {
    "deposit": "📥",
    "withdraw": "📤",
    "refund": "🔄",
    "payment": "💳",
}


async def history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /history 命令"""
    await _show_history(update, page=1)


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
    lang = await get_user_lang_from_update(update)
    telegram_id = update.effective_user.id

    async with async_session_maker() as session:
        svc = BalanceService(session)
        all_txs = await svc.get_user_transactions(telegram_id, skip=0, limit=1000)

    total = len(all_txs)
    if total == 0:
        text = tr("history.title", lang) + "\n\n" + tr("history.empty", lang)
        if edit:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return

    total_pages, offset, limit = paginate(total, page, PER_PAGE)
    page_txs = all_txs[offset : offset + limit]

    lines = [tr("history.title", lang), ""]
    for tx in page_txs:
        t_type = tx.transaction_type
        icon = _TYPE_ICONS.get(t_type, "📋")
        type_key = f"history.type_{t_type}"
        type_name = tr(type_key, lang)
        if type_name == type_key:
            type_name = t_type

        lines.append(
            tr(
                "history.entry",
                lang,
                icon=icon,
                type_name=type_name,
                amount=format_amount(tx.amount_usd),
                time=format_datetime(tx.created_at),
            )
        )

    lines.append("")
    lines.append(tr("history.page", lang, current=page, total=total_pages))

    text = "\n".join(lines)
    keyboard = pagination_keyboard(page, total_pages, "history_page", lang)

    if edit:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard)
    else:
        await update.message.reply_text(text, reply_markup=keyboard)
