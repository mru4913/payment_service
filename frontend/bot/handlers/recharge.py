#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
/recharge 充值流程（经 FastAPI HTTP，不直连数据库）。

流程：
  /recharge → 选 USD 金额 → 创建 Plisio invoice → 展示支付链接
  callback: recharge:amount:<n> / recharge:custom / recharge:status
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

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
    home_back_keyboard,
    plisio_invoice_keyboard,
    recharge_amount_keyboard,
)
from frontend.bot.navigation import edit_to_dashboard_home
from frontend.core.utils import format_amount, get_user_lang_from_update, tr
from frontend.integrations import BackendAPIError, get_backend_client
from common.logger import get_logger

logger = get_logger("frontend_bot")

SELECTING_AMOUNT = 0
WAITING_CUSTOM_AMOUNT = 1

MIN_AMOUNT = Decimal("1")
MAX_AMOUNT = Decimal("10000")
_ACTIVE_PANEL_CHAT_ID = "recharge_active_panel_chat_id"
_ACTIVE_PANEL_MESSAGE_ID = "recharge_active_panel_message_id"


def _backend_error_reply(lang: str, exc: BackendAPIError) -> str:
    if exc.is_transport:
        return tr("errors.backend_transport", lang)
    if exc.http_status in (401, 403):
        return tr("errors.backend_auth", lang)
    return tr("common.error", lang)


def _message_chat_id(message: Any) -> int | str | None:
    chat_id = getattr(message, "chat_id", None)
    if chat_id is not None:
        return chat_id
    chat = getattr(message, "chat", None)
    return getattr(chat, "id", None)


def _remember_active_panel(context: ContextTypes.DEFAULT_TYPE, message: Any) -> None:
    chat_id = _message_chat_id(message)
    message_id = getattr(message, "message_id", None)
    if chat_id is None or message_id is None:
        return
    context.user_data[_ACTIVE_PANEL_CHAT_ID] = chat_id
    context.user_data[_ACTIVE_PANEL_MESSAGE_ID] = message_id


async def _retire_active_panel(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = context.user_data.pop(_ACTIVE_PANEL_CHAT_ID, None)
    message_id = context.user_data.pop(_ACTIVE_PANEL_MESSAGE_ID, None)
    if chat_id is None or message_id is None:
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as exc:  # noqa: BLE001
        logger.info(
            "bot_recharge_panel_retire_failed chat_id=%s message_id=%s error=%s",
            chat_id,
            message_id,
            exc,
        )


async def _reply_active_panel(
    msg: Any,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    **kwargs: Any,
) -> Any:
    await _retire_active_panel(context)
    sent = await msg.reply_text(text, **kwargs)
    _remember_active_panel(context, sent)
    return sent


async def _edit_active_panel(
    query: Any,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    **kwargs: Any,
) -> Any:
    result = await query.edit_message_text(text, **kwargs)
    if query.message:
        _remember_active_panel(context, query.message)
    return result


async def recharge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /recharge 命令"""
    lang = await get_user_lang_from_update(update)
    telegram_id = update.effective_user.id
    query = update.callback_query
    msg = update.effective_message
    if query:
        await query.answer()
    client = get_backend_client()

    try:
        pending_data = await client.list_pending_payments(
            telegram_id=telegram_id, limit=200
        )
    except BackendAPIError as e:
        text = _backend_error_reply(lang, e)
        if query:
            await _edit_active_panel(query, context, text)
        elif msg:
            await _reply_active_panel(msg, context, text)
        return ConversationHandler.END

    payments = pending_data.get("payments") or []
    user_pending = [p for p in payments if p.get("payment_method") == "plisio_invoice"]
    if user_pending:
        p = user_pending[0]
        if query:
            await _show_plisio_invoice_order(query, context, p, lang, existing=True)
        elif msg:
            await _show_plisio_invoice_order(msg, context, p, lang, existing=True)
        return ConversationHandler.END

    keyboard = recharge_amount_keyboard(lang)
    if query:
        await _edit_active_panel(
            query,
            context,
            tr("recharge.select_amount", lang),
            reply_markup=keyboard,
        )
    elif msg:
        await _reply_active_panel(
            msg,
            context,
            tr("recharge.select_amount", lang),
            reply_markup=keyboard,
        )
    return SELECTING_AMOUNT


async def amount_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理金额选择回调"""
    query = update.callback_query
    await query.answer()
    data = query.data

    lang = await get_user_lang_from_update(update)

    if data == "recharge:custom":
        await _edit_active_panel(
            query,
            context,
            tr("recharge.enter_amount", lang),
            reply_markup=home_back_keyboard(lang, callback_data="recharge:home"),
        )
        return WAITING_CUSTOM_AMOUNT

    try:
        amount = Decimal(data.split(":")[-1])
    except (InvalidOperation, IndexError):
        await _edit_active_panel(query, context, tr("recharge.invalid_amount", lang))
        return ConversationHandler.END

    await _create_recharge_order(query, context, update.effective_user.id, amount, lang)
    return ConversationHandler.END


async def recharge_home_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """充值流程内返回首页。"""
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    lang = await get_user_lang_from_update(update)
    await edit_to_dashboard_home(
        query,
        context,
        lang,
        active_panel_keys=(_ACTIVE_PANEL_CHAT_ID, _ACTIVE_PANEL_MESSAGE_ID),
    )
    return ConversationHandler.END


async def custom_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户输入的自定义金额"""
    lang = await get_user_lang_from_update(update)
    text = update.message.text.strip()

    try:
        amount = Decimal(text)
    except InvalidOperation:
        await _reply_active_panel(
            update.message,
            context,
            tr("recharge.invalid_amount", lang),
        )
        return ConversationHandler.END

    if amount < MIN_AMOUNT or amount > MAX_AMOUNT:
        await _reply_active_panel(
            update.message,
            context,
            tr("recharge.invalid_amount", lang),
        )
        return ConversationHandler.END

    await _create_recharge_order(
        update.message,
        context,
        update.effective_user.id,
        amount,
        lang,
    )
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
        await _edit_active_panel(query, context, _backend_error_reply(lang, e))
        return

    if int(payment.get("telegram_id", -1)) != telegram_id:
        await query.answer()
        await _edit_active_panel(query, context, tr("common.error", lang))
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
        await _edit_active_panel(
            query,
            context,
            tr(
                "recharge.success",
                lang,
                amount=format_amount(amt),
                balance=format_amount(bal_dec),
            )
        )
    elif status == "cancelled":
        await query.answer()
        await _edit_active_panel(query, context, tr("recharge.cancelled", lang))
    elif status == "failed":
        await query.answer()
        await _edit_active_panel(query, context, tr("common.error", lang))
    else:
        await query.answer(tr("recharge.waiting", lang), show_alert=True)


async def _create_recharge_order(
    message_or_query,
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
    amount: Decimal,
    lang: str,
):
    """创建 Plisio invoice 充值订单。"""
    client = get_backend_client()
    try:
        created = await client.create_plisio_recharge_payment(
            telegram_id,
            amount,
            description=tr("recharge.description", lang),
        )
    except BackendAPIError as e:
        err = _backend_error_reply(lang, e)
        if e.http_status == 400 and e.message and not e.is_transport:
            err = tr("common.error", lang) + f"\n{e.message}"
        if hasattr(message_or_query, "edit_message_text"):
            await _edit_active_panel(message_or_query, context, err)
        else:
            await _reply_active_panel(message_or_query, context, err)
        return

    await _show_plisio_invoice_order(
        message_or_query,
        context,
        created,
        lang,
        existing=False,
    )


async def _show_plisio_invoice_order(
    message_or_query,
    context: ContextTypes.DEFAULT_TYPE,
    payment: dict,
    lang: str,
    *,
    existing: bool,
) -> None:
    meta = payment.get("metadata") or {}
    invoice_url = str(meta.get("invoice_url") or "")
    payment_id = str(payment.get("payment_id", ""))
    if not invoice_url or not payment_id:
        err = tr("common.error", lang)
        if hasattr(message_or_query, "edit_message_text"):
            await _edit_active_panel(message_or_query, context, err)
        else:
            await _reply_active_panel(message_or_query, context, err)
        return

    amount = Decimal(str(payment.get("amount_usd", meta.get("source_amount_usd", "0"))))
    currency = str(meta.get("currency") or meta.get("psys_cid") or "USDT_TRX")
    minutes = int(meta.get("expire_minutes") or 60)
    text_key = "recharge.pending_invoice_exists" if existing else "recharge.invoice"
    body = tr(
        text_key,
        lang,
        amount=format_amount(amount),
        currency=currency,
        minutes=minutes,
    )
    text = body if existing else f"{tr('recharge.order_created', lang)}\n\n{body}"

    keyboard = plisio_invoice_keyboard(payment_id, invoice_url, lang)
    reply = getattr(message_or_query, "edit_message_text", None)
    if reply:
        await _edit_active_panel(
            message_or_query,
            context,
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    else:
        await _reply_active_panel(
            message_or_query,
            context,
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )


def get_recharge_conversation_handler() -> ConversationHandler:
    """返回充值流程的 ConversationHandler"""
    return ConversationHandler(
        entry_points=[
            CommandHandler("recharge", recharge_command),
            CallbackQueryHandler(recharge_command, pattern=r"^dashboard:recharge$"),
        ],
        states={
            SELECTING_AMOUNT: [
                CallbackQueryHandler(
                    recharge_home_callback,
                    pattern=r"^recharge:home$",
                ),
                CallbackQueryHandler(
                    amount_callback, pattern=r"^recharge:(amount|custom)(:|$)"
                ),
            ],
            WAITING_CUSTOM_AMOUNT: [
                CallbackQueryHandler(
                    recharge_home_callback,
                    pattern=r"^recharge:home$",
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, custom_amount_input),
            ],
        },
        fallbacks=[
            CommandHandler("recharge", recharge_command),
        ],
        per_message=False,
    )
