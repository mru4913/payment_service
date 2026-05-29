#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Telegram native workflow for watermark and logo removal."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from common.compute_catalog import ComputeCatalogError, estimate_hold_amount
from common.logger import get_logger
from common.task_refs import public_task_code
from frontend.bot.dashboard_view import dashboard_text_for_user
from frontend.bot.keyboards import dashboard_keyboard
from frontend.bot.navigation import edit_to_dashboard_home
from frontend.core.utils import get_user_lang_from_update, tr
from frontend.integrations import (
    BackendAPIError,
    get_backend_client,
    task_body_for_create,
)

ASK_IMAGE, CONFIRM = range(2)

_TASK_TYPE = "remove_watermark"
_PLATFORM = "runninghub"
_DEFAULT_PRIORITY = "default"
_PRIORITY_TYPES = ("lite", "default", "plus")
_ACTIVE_PANEL_CHAT_ID = "remove_watermark_active_panel_chat_id"
_ACTIVE_PANEL_MESSAGE_ID = "remove_watermark_active_panel_message_id"

logger = get_logger("frontend_bot")


def _buttons(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(text, callback_data=callback)
                for text, callback in row
            ]
            for row in rows
        ]
    )


def _priority_label(priority: str, lang: str) -> str:
    key = {
        "lite": "compute.priority_lite",
        "default": "compute.priority_default",
        "plus": "compute.priority_plus",
    }.get(priority, "compute.priority_default")
    return tr(key, lang)


def _current_hold(context: ContextTypes.DEFAULT_TYPE) -> Decimal:
    priority = str(
        context.user_data.get("remove_watermark_priority", _DEFAULT_PRIORITY)
    )
    try:
        return estimate_hold_amount(_TASK_TYPE, priority)
    except ComputeCatalogError:
        logger.exception(
            "bot_remove_watermark_hold_estimate_failed task_type=%s priority=%s",
            _TASK_TYPE,
            priority,
        )
        return Decimal("0.216000")


def _task_input_payload(context: ContextTypes.DEFAULT_TYPE) -> dict[str, str]:
    return {
        "image": str(context.user_data.get("remove_watermark_image") or ""),
    }


def _telegram_id(update: Update) -> int | str:
    return update.effective_user.id if update.effective_user else "unknown"


def _flow_id(context: ContextTypes.DEFAULT_TYPE) -> str:
    return str(context.user_data.get("remove_watermark_flow_id") or "-")


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
            "bot_remove_watermark_panel_retire_failed flow_id=%s chat_id=%s "
            "message_id=%s error=%s",
            _flow_id(context),
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


def _image_keyboard(lang: str, *, can_next: bool) -> InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = []
    if can_next:
        rows.append(
            [
                (
                    tr("remove_watermark.btn_next_confirm", lang),
                    "remove_watermark:image_next",
                )
            ]
        )
    rows.append([(tr("compute.btn_cancel_task", lang), "remove_watermark:cancel")])
    return _buttons(rows)


def _confirm_keyboard(
    context: ContextTypes.DEFAULT_TYPE,
    lang: str,
) -> InlineKeyboardMarkup:
    priority = str(
        context.user_data.get("remove_watermark_priority", _DEFAULT_PRIORITY)
    )
    return _buttons(
        [
            [(tr("compute.btn_start_generate", lang), "remove_watermark:start")],
            [
                (
                    f"{tr('compute.priority_lite', lang)}"
                    f"{' ✓' if priority == 'lite' else ''}",
                    "remove_watermark:priority:lite",
                ),
                (
                    f"{tr('compute.priority_default', lang)}"
                    f"{' ✓' if priority == 'default' else ''}",
                    "remove_watermark:priority:default",
                ),
                (
                    f"{tr('compute.priority_plus', lang)}"
                    f"{' ✓' if priority == 'plus' else ''}",
                    "remove_watermark:priority:plus",
                ),
            ],
            [(tr("compute.btn_cancel_task", lang), "remove_watermark:cancel")],
        ]
    )


def _task_card_keyboard(task_id: str, lang: str) -> InlineKeyboardMarkup:
    return _buttons(
        [
            [(tr("common.btn_check_status", lang), f"compute:status:{task_id}")],
            [
                (
                    tr("remove_watermark.btn_new_task", lang),
                    "remove_watermark:restart",
                )
            ],
            [(f"↩️ {tr('common.btn_back', lang)}", "dashboard:home")],
        ]
    )


def _image_attachment(update: Update) -> tuple[str, str, str] | None:
    msg = update.effective_message
    if not msg:
        return None
    if msg.photo:
        p = msg.photo[-1]
        return p.file_id, f"{p.file_unique_id}.jpg", "image/jpeg"
    doc = msg.document
    if doc and (doc.mime_type or "").startswith("image/"):
        filename = doc.file_name or f"{doc.file_unique_id}.jpg"
        return doc.file_id, filename, doc.mime_type or "image/jpeg"
    return None


async def _upload_image(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> str | None:
    attachment = _image_attachment(update)
    if attachment is None:
        logger.info(
            "bot_remove_watermark_upload_ignored telegram_id=%s flow_id=%s "
            "reason=no_image",
            _telegram_id(update),
            _flow_id(context),
        )
        return None
    file_id, filename, content_type = attachment
    tg_file = await context.bot.get_file(file_id)
    content = bytes(await tg_file.download_as_bytearray())
    logger.info(
        "bot_remove_watermark_upload_start telegram_id=%s flow_id=%s filename=%s "
        "content_type=%s bytes=%s",
        _telegram_id(update),
        _flow_id(context),
        filename,
        content_type,
        len(content),
    )
    data = await get_backend_client().upload_media(
        content=content,
        filename=filename,
        content_type=content_type,
    )
    file_ref = str(data.get("file_ref") or "")
    logger.info(
        "bot_remove_watermark_upload_done telegram_id=%s flow_id=%s filename=%s "
        "has_file_ref=%s",
        _telegram_id(update),
        _flow_id(context),
        filename,
        bool(file_ref),
    )
    return file_ref


async def remove_watermark_image(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    lang = await get_user_lang_from_update(update)
    msg = update.effective_message
    if not msg:
        return ASK_IMAGE
    if context.user_data.get("remove_watermark_image"):
        await _reply_active_panel(
            msg,
            context,
            tr("remove_watermark.image_already_received", lang),
            reply_markup=_image_keyboard(lang, can_next=True),
        )
        return ASK_IMAGE
    try:
        file_ref = await _upload_image(update, context)
    except BackendAPIError as e:
        await _reply_backend_error(msg, lang, e)
        return ASK_IMAGE
    if not file_ref:
        await _reply_active_panel(
            msg,
            context,
            tr("compute.invalid_image", lang),
            reply_markup=_image_keyboard(lang, can_next=False),
        )
        return ASK_IMAGE

    context.user_data["remove_watermark_image"] = file_ref
    logger.info(
        "bot_remove_watermark_image_received telegram_id=%s flow_id=%s",
        _telegram_id(update),
        _flow_id(context),
    )
    await _reply_active_panel(
        msg,
        context,
        tr("remove_watermark.image_received", lang),
        reply_markup=_image_keyboard(lang, can_next=True),
    )
    return ASK_IMAGE


async def remove_watermark_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    lang = await get_user_lang_from_update(update)
    data = query.data or ""

    if data == "remove_watermark:cancel":
        logger.info(
            "bot_remove_watermark_cancel telegram_id=%s flow_id=%s source=callback",
            _telegram_id(update),
            _flow_id(context),
        )
        context.user_data.clear()
        await edit_to_dashboard_home(query, context, lang)
        return ConversationHandler.END

    if data == "remove_watermark:image_next":
        if not context.user_data.get("remove_watermark_image"):
            await _edit_active_panel(
                query,
                context,
                tr("remove_watermark.need_image", lang),
                reply_markup=_image_keyboard(lang, can_next=False),
            )
            return ASK_IMAGE
        await _show_confirm(query, context, lang)
        return CONFIRM

    if data.startswith("remove_watermark:priority:"):
        priority = data.rsplit(":", 1)[-1]
        if priority in _PRIORITY_TYPES:
            context.user_data["remove_watermark_priority"] = priority
            logger.info(
                "bot_remove_watermark_priority_select telegram_id=%s flow_id=%s "
                "priority=%s",
                _telegram_id(update),
                _flow_id(context),
                priority,
            )
        await _show_confirm(query, context, lang)
        return CONFIRM

    if data == "remove_watermark:start":
        return await _start_task(query, context, lang)

    return CONFIRM


async def remove_watermark_restart_entry(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    lang = await get_user_lang_from_update(update)
    await _restart_from_query(query, context, lang)
    return ASK_IMAGE


async def _restart_from_query(
    query: Any,
    context: ContextTypes.DEFAULT_TYPE,
    lang: str,
) -> None:
    context.user_data.clear()
    context.user_data["remove_watermark_flow_id"] = uuid4().hex
    context.user_data["remove_watermark_priority"] = _DEFAULT_PRIORITY
    await _edit_active_panel(
        query,
        context,
        tr("remove_watermark.ask_image", lang),
        parse_mode="HTML",
        reply_markup=_image_keyboard(lang, can_next=False),
    )


async def _show_confirm(
    query: Any,
    context: ContextTypes.DEFAULT_TYPE,
    lang: str,
) -> None:
    priority = str(
        context.user_data.get("remove_watermark_priority", _DEFAULT_PRIORITY)
    )
    await _edit_active_panel(
        query,
        context,
        tr(
            "remove_watermark.confirm",
            lang,
            priority=_priority_label(priority, lang),
            hold=str(_current_hold(context)),
        ),
        parse_mode="HTML",
        reply_markup=_confirm_keyboard(context, lang),
    )


async def _start_task(query: Any, context: ContextTypes.DEFAULT_TYPE, lang: str) -> int:
    if not query.message or not query.from_user:
        return ConversationHandler.END
    payload = _task_input_payload(context)
    if not payload["image"]:
        await _edit_active_panel(
            query,
            context,
            tr("remove_watermark.missing_inputs", lang),
        )
        return ConversationHandler.END

    priority = str(
        context.user_data.get("remove_watermark_priority", _DEFAULT_PRIORITY)
    )
    hold = _current_hold(context)
    body = task_body_for_create(
        telegram_id=query.from_user.id,
        task_type=_TASK_TYPE,
        third_party_platform=_PLATFORM,
        priority_type=priority,
        input_payload=payload,
    )

    try:
        logger.info(
            "bot_remove_watermark_create_task_start telegram_id=%s flow_id=%s "
            "priority=%s hold=%s",
            query.from_user.id,
            _flow_id(context),
            priority,
            hold,
        )
        data = await get_backend_client().create_task(body)
    except BackendAPIError as e:
        logger.warning(
            "bot_remove_watermark_create_task_failed telegram_id=%s flow_id=%s "
            "http_status=%s code=%s transport=%s",
            query.from_user.id,
            _flow_id(context),
            e.http_status,
            e.code,
            e.is_transport,
        )
        await _reply_backend_error(query.message, lang, e)
        context.user_data.clear()
        return ConversationHandler.END

    task_id = str(data.get("task_id", ""))
    task_code = str(data.get("task_code") or public_task_code(task_id))
    status = str(data.get("status", ""))
    logger.info(
        "bot_remove_watermark_create_task_done telegram_id=%s flow_id=%s "
        "task_id=%s status=%s priority=%s hold=%s",
        query.from_user.id,
        _flow_id(context),
        task_id,
        status,
        priority,
        hold,
    )
    await _edit_active_panel(
        query,
        context,
        tr(
            "remove_watermark.success",
            lang,
            task_code=task_code,
            status=status,
            priority=_priority_label(priority, lang),
            hold=str(hold),
        ),
        parse_mode="HTML",
        reply_markup=_task_card_keyboard(task_id, lang),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def _reply_backend_error(msg: Any, lang: str, err: BackendAPIError) -> None:
    if err.is_transport:
        await msg.reply_text(tr("errors.backend_transport", lang))
    elif err.http_status in (401, 403):
        await msg.reply_text(tr("errors.backend_auth", lang))
    elif err.code == "insufficient_funds":
        await msg.reply_text(err.message or tr("common.error", lang))
    else:
        await msg.reply_text(err.message or tr("common.error", lang))


async def remove_watermark_cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    lang = await get_user_lang_from_update(update)
    msg = update.effective_message
    if msg:
        logger.info(
            "bot_remove_watermark_cancel telegram_id=%s flow_id=%s source=command",
            _telegram_id(update),
            _flow_id(context),
        )
        await _retire_active_panel(context)
        if update.effective_user:
            await msg.reply_text(
                await dashboard_text_for_user(
                    lang,
                    update.effective_user.id,
                    update.effective_user.first_name,
                ),
                reply_markup=dashboard_keyboard(lang),
                parse_mode="HTML",
            )
        else:
            await msg.reply_text(tr("compute.cancelled", lang))
    context.user_data.clear()
    return ConversationHandler.END


def get_remove_watermark_conversation_handler() -> ConversationHandler:
    image_filter = filters.PHOTO | filters.Document.IMAGE
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                remove_watermark_restart_entry,
                pattern=r"^(remove_watermark:restart|dashboard:remove_watermark)$",
            ),
        ],
        states={
            ASK_IMAGE: [
                MessageHandler(image_filter, remove_watermark_image),
                CallbackQueryHandler(
                    remove_watermark_callback,
                    pattern=r"^remove_watermark:",
                ),
            ],
            CONFIRM: [
                CallbackQueryHandler(
                    remove_watermark_callback,
                    pattern=r"^remove_watermark:",
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", remove_watermark_cancel)],
        name="remove_watermark_create",
        allow_reentry=True,
    )
