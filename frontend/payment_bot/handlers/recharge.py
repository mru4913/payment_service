#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
/recharge 充值流程

流程：
  /recharge → 选金额键盘 → 创建订单 → 展示收款地址
  callback: recharge:amount:<n> / recharge:custom / recharge:status / recharge:cancel
"""

from decimal import Decimal, InvalidOperation

from telegram import Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from backend.database.session import async_session_maker
from backend.services.payment_service import PaymentService
from backend.payments.trc20_usdt import TRC20UsdtProvider
from backend.payments.base import PaymentRequest
from frontend.core.utils import get_user_lang_from_update, tr, format_amount
from frontend.payment_bot.keyboards import (
    recharge_amount_keyboard,
    recharge_order_keyboard,
)

# ConversationHandler 状态：先选金额，可选「自定义」再等待文本输入
SELECTING_AMOUNT = 0
WAITING_CUSTOM_AMOUNT = 1

MIN_AMOUNT = Decimal("1")
MAX_AMOUNT = Decimal("10000")


async def recharge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /recharge 命令"""
    lang = await get_user_lang_from_update(update)
    telegram_id = update.effective_user.id

    # 检查是否有未完成的 trc20_usdt 订单
    async with async_session_maker() as session:
        svc = PaymentService(session)
        pending = await svc.get_pending_payments(limit=200)
        user_pending = [
            p
            for p in pending
            if p.telegram_id == telegram_id and p.payment_method == "trc20_usdt"
        ]
        if user_pending:
            p = user_pending[0]
            await update.message.reply_text(
                tr("recharge.pending_exists", lang, amount=format_amount(p.amount_usd))
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

    # recharge:amount:<n>
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

    async with async_session_maker() as session:
        svc = PaymentService(session)
        payment = await svc.get_payment(payment_id)

    if not payment or payment.telegram_id != telegram_id:
        await query.answer()
        await query.edit_message_text(tr("common.error", lang))
        return

    if payment.status == "completed":
        await query.answer()
        async with async_session_maker() as session:
            from backend.services.user_service import UserService

            user_svc = UserService(session)
            user_balance = await user_svc.get_user_balance(payment.telegram_id)
        await query.edit_message_text(
            tr(
                "recharge.success",
                lang,
                amount=format_amount(payment.amount_usd),
                balance=format_amount(user_balance or Decimal("0")),
            )
        )
    elif payment.status == "cancelled":
        await query.answer()
        await query.edit_message_text(tr("recharge.cancelled", lang))
    else:
        # 每个 callback 只能 answer 一次；pending 用弹窗提示，不重复 answer
        await query.answer("⏳ 等待到账中…", show_alert=True)


async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消订单"""
    query = update.callback_query
    await query.answer()
    payment_id = query.data.split(":")[-1]
    lang = await get_user_lang_from_update(update)
    telegram_id = update.effective_user.id

    async with async_session_maker() as session:
        svc = PaymentService(session)
        payment = await svc.get_payment(payment_id)
        if not payment or payment.telegram_id != telegram_id:
            await query.edit_message_text(tr("common.error", lang))
            return
        cancelled = await svc.cancel_payment(payment_id)
        if not cancelled:
            await query.edit_message_text(tr("common.error", lang))
            return

    await query.edit_message_text(tr("recharge.cancel_confirm", lang))


async def _create_recharge_order(
    message_or_query, telegram_id: int, amount: Decimal, lang: str
):
    """创建 TRC20 USDT 充值订单的核心逻辑"""
    provider = TRC20UsdtProvider()

    async with async_session_maker() as session:
        request = PaymentRequest(
            payment_id="temp",
            amount_usd=amount,
            description="TRC20 USDT Recharge",
            callback_url="",
        )
        result = await provider.create_unique_payment(request, session)

        if not result.success:
            error_text = tr("common.error", lang) + f"\n{result.error_message}"
            if hasattr(message_or_query, "edit_message_text"):
                await message_or_query.edit_message_text(error_text)
            else:
                await message_or_query.reply_text(error_text)
            return

        unique_amount = Decimal(result.metadata["amount_usdt"])
        wallet_address = result.metadata["wallet_address"]

        svc = PaymentService(session)
        payment = await svc.create_payment(
            telegram_id=telegram_id,
            amount_usd=unique_amount,
            payment_method="trc20_usdt",
            description="TRC20 USDT Recharge",
            payment_metadata=result.metadata,
        )
        await session.commit()

    from backend.globals import settings

    timeout = settings.trc20_order_timeout_minutes

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

    keyboard = recharge_order_keyboard(str(payment.payment_id), lang)

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
