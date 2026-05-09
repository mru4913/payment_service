#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
/balance 余额查询
"""

from telegram import Update
from telegram.ext import ContextTypes

from backend.database.session import async_session_maker
from backend.services.user_service import UserService
from frontend.core.utils import get_user_lang_from_update, tr, format_amount


async def balance_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /balance 命令"""
    lang = await get_user_lang_from_update(update)
    telegram_id = update.effective_user.id

    async with async_session_maker() as session:
        svc = UserService(session)
        stats = await svc.get_user_stats(telegram_id)

    if not stats:
        await update.message.reply_text(tr("common.error", lang))
        return

    text = (
        tr("balance.title", lang)
        + "\n\n"
        + tr("balance.current", lang, balance=format_amount(stats["balance"]))
        + "\n"
        + tr(
            "balance.total_deposit",
            lang,
            deposits=format_amount(stats["total_deposits"]),
        )
        + "\n"
        + tr(
            "balance.total_withdraw",
            lang,
            withdrawals=format_amount(stats["total_withdrawals"]),
        )
    )
    await update.message.reply_text(text, parse_mode="HTML")
