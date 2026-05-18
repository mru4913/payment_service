#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
/recharge 充值流程（经 FastAPI HTTP，不直连数据库）。

流程：
  /recharge → 选金额键盘 → 创建订单 → 展示收款地址
  callback: recharge:amount:<n> / recharge:custom / recharge:status / recharge:cancel
"""

from decimal import Decimal, InvalidOperation

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from frontend.bot.keyboards import (
    recharge_amount_keyboard,
    recharge_order_keyboard,
)
from frontend.core.utils import format_amount, get_user_lang_from_update, tr
from frontend.integrations import BackendAPIError, get_backend_client

SELECTING_AMOUNT = 0
WAITING_CUSTOM_AMOUNT = 1

MIN_AMOUNT = Decimal("1")
MAX_AMOUNT = Decimal("10000")


def _backend_error_reply(lang: str, exc: BackendAPIError) -> str:
    if exc.is_transport:
        return tr("errors.backend_transport", lang)
    if exc.http_status in (401, 403):
        return tr("errors.backend_auth", lang)
    return tr("common.error", lang)


async def recharge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /recharge 命令"""
    lang = await get_user_lang_from_update(update)
    telegram_id = update.effective_user.id
    client = get_backend_client()

    try:
        pending_data = await client.list_pending_payments(
            telegram_id=telegram_id, limit=200
        )
    except BackendAPIError as e:
        await update.message.reply_text(_backend_error_reply(lang, e))
        return ConversationHandler.END

    payments = pending_data.get("payments") or []
    user_pending = [p for p in payments if p.get("payment_method") == "trc20_usdt"]
    if user_pending:
        p = user_pending[0]
        amt = Decimal(str(p.get("amount_usd", "0")))
        await update.message.reply_text(
            tr("recharge.pending_exists", lang, amount=format_amount(amt))
        )
        return ConversationHandler.END

    keyboard = recharge_amount_keyboard(lang)
    await update.message.reply_text(
        tr("recharge.select_amount", lang), reply_markup=keyboard
    )
    return SELECTING_AMOUNT


async def amount_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理金额选择回调"""
    query = update.callback_query
    await query.answer()
    data = query.data

    lang = await get_user_lang_from_update(update)

    if data == "recharge:custom":
        await query.edit_message_text(tr("recharge.enter_amount", lang))
        return WAITING_CUSTOM_AMOUNT

    try:
        amount = Decimal(data.split(":")[-1])
    except (InvalidOperation, IndexError):
        await query.edit_message_text(tr("recharge.invalid_amount", lang))
        return ConversationHandler.END

    await _create_recharge_order(query, update.effective_user.id, amount, lang)
    return ConversationHandler.END


async def custom_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户输入的自定义金额"""
    lang = await get_user_lang_from_update(update)
    text = update.message.text.strip()

    try:
        amount = Decimal(text)
    except InvalidOperation:
        await update.message.reply_text(tr("recharge.invalid_amount", lang))
        return ConversationHandler.END

    if amount < MIN_AMOUNT or amount > MAX_AMOUNT:
        await update.message.reply_text(tr("recharge.invalid_amount", lang))
        return ConversationHandler.END

    await _create_recharge_order(update.message, update.effective_user.id, amount, lang)
    return ConversationHandler.END


async def status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查询订单状态"""
    query = update.callback_query
    payment_id = query.data.split(":")[-1]
    lang = await get_user_lang_from_update(update)
    telegram_id = update.effective_user.id
    client = get_backend_client()

    try:
        payment = await client.get_payment(payment_id)
    except BackendAPIError as e:
        await query.answer()
        await query.edit_message_text(_backend_error_reply(lang, e))
        return

    if int(payment.get("telegram_id", -1)) != telegram_id:
        await query.answer()
        await query.edit_message_text(tr("common.error", lang))
        return

    status = payment.get("status")
    if status == "completed":
        await query.answer()
        try:
            bal = await client.get_user_balance(telegram_id)
            bal_dec = Decimal(str(bal.get("balance", "0")))
        except BackendAPIError:
            bal_dec = Decimal("0")
        amt = Decimal(str(payment.get("amount_usd", "0")))
        await query.edit_message_text(
            tr(
                "recharge.success",
                lang,
                amount=format_amount(amt),
                balance=format_amount(bal_dec),
            )
        )
    elif status == "cancelled":
        await query.answer()
        await query.edit_message_text(tr("recharge.cancelled", lang))
    else:
        await query.answer("⏳ 等待到账中…", show_alert=True)


async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消订单"""
    query = update.callback_query
    await query.answer()
    payment_id = query.data.split(":")[-1]
    lang = await get_user_lang_from_update(update)
    telegram_id = update.effective_user.id
    client = get_backend_client()

    try:
        pay = await client.get_payment(payment_id)
        if int(pay.get("telegram_id", -1)) != telegram_id:
            await query.edit_message_text(tr("common.error", lang))
            return
        await client.cancel_payment(payment_id)
    except BackendAPIError:
        await query.edit_message_text(tr("common.error", lang))
        return

    await query.edit_message_text(tr("recharge.cancel_confirm", lang))


async def _create_recharge_order(
    message_or_query, telegram_id: int, amount: Decimal, lang: str
):
    """创建 TRC20 USDT 充值订单（服务端唯一金额 + metadata）。"""
    client = get_backend_client()
    try:
        created = await client.create_trc20_recharge_payment(
            telegram_id,
            amount,
            description="TRC20 USDT Recharge",
        )
    except BackendAPIError as e:
        err = _backend_error_reply(lang, e)
        if e.http_status == 400 and e.message and not e.is_transport:
            err = tr("common.error", lang) + f"\n{e.message}"
        if hasattr(message_or_query, "edit_message_text"):
            await message_or_query.edit_message_text(err)
        else:
            await message_or_query.reply_text(err)
        return

    meta = created.get("metadata") or {}
    raw_amt = meta.get("amount_usdt")
    wallet_address = meta.get("wallet_address")
    if raw_amt is None or not wallet_address:
        err = tr("common.error", lang)
        if hasattr(message_or_query, "edit_message_text"):
            await message_or_query.edit_message_text(err)
        else:
            await message_or_query.reply_text(err)
        return

    unique_amount = Decimal(str(raw_amt))
    timeout = int(created.get("order_timeout_minutes") or 15)
    payment_id = str(created.get("payment_id", ""))

    text = (
        tr("recharge.order_created", lang)
        + "\n\n"
        + tr(
            "recharge.confirm",
            lang,
            amount=format_amount(unique_amount),
            address=wallet_address,
        )
        + "\n\n"
        + tr("recharge.timeout_warning", lang, minutes=timeout)
    )

    keyboard = recharge_order_keyboard(payment_id, lang)

    reply = getattr(message_or_query, "edit_message_text", None)
    if reply:
        await reply(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await message_or_query.reply_text(
            text, reply_markup=keyboard, parse_mode="HTML"
        )


def get_recharge_conversation_handler() -> ConversationHandler:
    """返回充值流程的 ConversationHandler"""
    return ConversationHandler(
        entry_points=[
            CommandHandler("recharge", recharge_command),
        ],
        states={
            SELECTING_AMOUNT: [
                CallbackQueryHandler(
                    amount_callback, pattern=r"^recharge:(amount|custom)(:|$)"
                ),
            ],
            WAITING_CUSTOM_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, custom_amount_input),
            ],
        },
        fallbacks=[
            CommandHandler("recharge", recharge_command),
        ],
        per_message=False,
    )
