#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
/balance 余额查询（经 FastAPI HTTP，不直连数据库）。
"""

from decimal import Decimal

from telegram import Update
from telegram.ext import ContextTypes

from frontend.core.utils import get_user_lang_from_update, tr, format_amount
from frontend.integrations import BackendAPIError, get_backend_client


async def balance_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /balance 命令"""
    msg = update.effective_message
    if not msg or not update.effective_user:
        return

    lang = await get_user_lang_from_update(update)
    telegram_id = update.effective_user.id
    client = get_backend_client()

    try:
        data = await client.get_user(telegram_id)
    except BackendAPIError as e:
        if e.http_status == 404:
            await msg.reply_text(tr("balance.user_not_found", lang))
            return
        if e.is_transport:
            await msg.reply_text(tr("errors.backend_transport", lang))
            return
        if e.http_status == 401 or e.http_status == 403:
            await msg.reply_text(tr("errors.backend_auth", lang))
            return
        await msg.reply_text(tr("common.error", lang))
        return

    balance = Decimal(str(data["balance"]))
    held = Decimal(str(data["balance_held"]))
    available = Decimal(str(data["balance_available"]))
    deposits = Decimal(str(data["total_deposits"]))
    withdrawals = Decimal(str(data["total_withdrawals"]))

    text = (
        tr("balance.title", lang)
        + "\n\n"
        + tr("balance.total", lang, balance=format_amount(balance))
        + "\n"
        + tr("balance.held", lang, held=format_amount(held))
        + "\n"
        + tr("balance.available", lang, available=format_amount(available))
        + "\n"
        + tr("balance.total_deposit", lang, deposits=format_amount(deposits))
        + "\n"
        + tr(
            "balance.total_withdraw",
            lang,
            withdrawals=format_amount(withdrawals),
        )
    )
    await msg.reply_text(text, parse_mode="HTML")
