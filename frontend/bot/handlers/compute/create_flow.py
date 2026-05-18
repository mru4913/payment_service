#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""/compute — 分步创建 face_swap 任务（POST /tasks）。"""

from decimal import Decimal

from telegram import Update
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from frontend.core.utils import get_user_lang_from_update, tr
from frontend.integrations import (
    BackendAPIError,
    get_backend_client,
    task_body_for_create,
)

ASK_SOURCE, ASK_TARGET = range(2)

_DEFAULT_HOLD = Decimal("5")
_TASK_TYPE = "face_swap"
_PLATFORM = "runninghub"


def _is_http_url(text: str) -> bool:
    t = text.strip()
    return t.startswith("http://") or t.startswith("https://")


async def compute_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    if not msg:
        return ConversationHandler.END

    lang = await get_user_lang_from_update(update)

    context.user_data["compute_priority"] = "default"
    context.user_data["compute_hold"] = _DEFAULT_HOLD

    intro = tr(
        "compute.intro",
        lang,
        hold=str(_DEFAULT_HOLD),
        priority=context.user_data["compute_priority"],
    )
    ask = tr("compute.ask_source", lang)
    await msg.reply_text(f"{intro}\n\n{ask}", parse_mode="HTML")
    return ASK_SOURCE


async def compute_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await get_user_lang_from_update(update)
    msg = update.effective_message
    if not msg:
        return ConversationHandler.END
    text = (msg.text or "").strip()
    if not _is_http_url(text):
        await msg.reply_text(tr("compute.invalid_url", lang))
        return ASK_SOURCE

    context.user_data["source_image"] = text.strip()
    await msg.reply_text(tr("compute.ask_target", lang), parse_mode="HTML")
    return ASK_TARGET


async def compute_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await get_user_lang_from_update(update)
    msg = update.effective_message
    if not msg or not update.effective_user:
        return ConversationHandler.END
    text = (msg.text or "").strip()
    if not _is_http_url(text):
        await msg.reply_text(tr("compute.invalid_url", lang))
        return ASK_TARGET

    telegram_id = update.effective_user.id
    hold: Decimal = context.user_data.get("compute_hold", _DEFAULT_HOLD)
    priority = context.user_data.get("compute_priority", "default")
    source = context.user_data.get("source_image", "")

    body = task_body_for_create(
        telegram_id=telegram_id,
        task_type=_TASK_TYPE,
        third_party_platform=_PLATFORM,
        priority_type=priority,
        input_payload={
            "source_image": source,
            "target_image": text.strip(),
        },
        hold_amount=hold,
    )

    client = get_backend_client()
    try:
        data = await client.create_task(body)
    except BackendAPIError as e:
        if e.is_transport:
            await msg.reply_text(tr("errors.backend_transport", lang))
        elif e.http_status in (401, 403):
            await msg.reply_text(tr("errors.backend_auth", lang))
        elif e.code == "insufficient_funds":
            rmsg = e.message or tr("common.error", lang)
            await msg.reply_text(rmsg)
        else:
            rmsg = e.message or tr("common.error", lang)
            await msg.reply_text(rmsg)
        context.user_data.clear()
        return ConversationHandler.END

    task_id = data.get("task_id", "")
    status = data.get("status", "")
    await msg.reply_text(
        tr("compute.success", lang, task_id=str(task_id), status=str(status)),
        parse_mode="HTML",
    )
    context.user_data.clear()
    return ConversationHandler.END


async def compute_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await get_user_lang_from_update(update)
    msg = update.effective_message
    if msg:
        await msg.reply_text(tr("compute.cancelled", lang))
    context.user_data.clear()
    return ConversationHandler.END


def get_compute_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("compute", compute_entry)],
        states={
            ASK_SOURCE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, compute_source),
            ],
            ASK_TARGET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, compute_target),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", compute_cancel),
        ],
        name="compute_create",
        allow_reentry=True,
    )
