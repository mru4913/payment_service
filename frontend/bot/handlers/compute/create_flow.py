#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Telegram 原生图片换脸流程。"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from frontend.bot.dashboard_view import dashboard_text_for_user
from frontend.bot.keyboards import dashboard_keyboard
from frontend.core.utils import get_user_lang_from_update, tr
from frontend.bot.navigation import edit_to_dashboard_home
from frontend.integrations import (
    BackendAPIError,
    get_backend_client,
    task_body_for_create,
)
from common.logger import get_logger
from common.compute_catalog import ComputeCatalogError, estimate_hold_amount
from common.task_refs import public_task_code

from .task_status import render_task_status, send_task_result_images

logger = get_logger("frontend_bot")

ASK_FACES, ASK_TARGET, CONFIRM = range(3)

_TASK_TYPE = "face_swap"
_PLATFORM = "runninghub"
_MAX_FACE_IMAGES = 4
_DEFAULT_PRIORITY = "default"
_DEFAULT_RESTORE = False
_PRIORITY_TYPES = ("lite", "default", "plus")
_ACTIVE_PANEL_CHAT_ID = "compute_active_panel_chat_id"
_ACTIVE_PANEL_MESSAGE_ID = "compute_active_panel_message_id"


def _priority_label(priority: str, lang: str) -> str:
    key = {
        "lite": "compute.priority_lite",
        "default": "compute.priority_default",
        "plus": "compute.priority_plus",
    }.get(priority, "compute.priority_default")
    return tr(key, lang)


def _current_hold(context: ContextTypes.DEFAULT_TYPE) -> Decimal:
    priority = context.user_data.get("compute_priority", _DEFAULT_PRIORITY)
    try:
        return estimate_hold_amount(_TASK_TYPE, str(priority))
    except ComputeCatalogError:
        logger.exception(
            "bot_compute_hold_estimate_failed task_type=%s priority=%s",
            _TASK_TYPE,
            priority,
        )
        return Decimal("0.180000")


def _face_refs(context: ContextTypes.DEFAULT_TYPE) -> list[str]:
    return list(context.user_data.get("face_images") or [])


def _telegram_id(update: Update) -> int | str:
    return update.effective_user.id if update.effective_user else "unknown"


def _flow_id(context: ContextTypes.DEFAULT_TYPE) -> str:
    value = context.user_data.get("compute_flow_id")
    if value:
        return str(value)
    return "-"


def _face_media_group_ids(context: ContextTypes.DEFAULT_TYPE) -> set[str]:
    return set(context.user_data.get("face_media_group_ids") or [])


def _message_media_group_id(update: Update) -> str | None:
    msg = update.effective_message
    if not msg:
        return None
    media_group_id = getattr(msg, "media_group_id", None)
    return str(media_group_id) if media_group_id else None


def _remember_face_media_group(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    media_group_id = _message_media_group_id(update)
    if not media_group_id:
        return
    group_ids = _face_media_group_ids(context)
    group_ids.add(media_group_id)
    context.user_data["face_media_group_ids"] = group_ids


def _is_from_face_media_group(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    media_group_id = _message_media_group_id(update)
    return bool(media_group_id and media_group_id in _face_media_group_ids(context))


def _buttons(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text, callback_data=callback)
            for text, callback in row
        ]
        for row in rows
    ]
    return InlineKeyboardMarkup(
        keyboard,
    )


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
            "bot_compute_panel_retire_failed flow_id=%s chat_id=%s "
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


def _faces_keyboard(lang: str, *, can_next: bool) -> InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = []
    if can_next:
        rows.append([(tr("compute.btn_next_target", lang), "compute:faces_next")])
    rows.append([(tr("compute.btn_cancel_task", lang), "compute:cancel")])
    return _buttons(rows)


def _target_keyboard(lang: str) -> InlineKeyboardMarkup:
    return _buttons(
        [
            [(tr("compute.btn_next_confirm", lang), "compute:target_next")],
            [(tr("compute.btn_cancel_task", lang), "compute:cancel")],
        ]
    )


def _confirm_keyboard(
    context: ContextTypes.DEFAULT_TYPE,
    lang: str,
) -> InlineKeyboardMarkup:
    restore = bool(context.user_data.get("restore", _DEFAULT_RESTORE))
    priority = str(context.user_data.get("compute_priority", _DEFAULT_PRIORITY))
    restore_label = tr("compute.restore_on" if restore else "compute.restore_off", lang)
    return _buttons(
        [
            [(tr("compute.btn_start_generate", lang), "compute:start")],
            [(restore_label, "compute:toggle_restore")],
            [
                (
                    f"{tr('compute.priority_lite', lang)}"
                    f"{' ✓' if priority == 'lite' else ''}",
                    "compute:priority:lite",
                ),
                (
                    f"{tr('compute.priority_default', lang)}"
                    f"{' ✓' if priority == 'default' else ''}",
                    "compute:priority:default",
                ),
                (
                    f"{tr('compute.priority_plus', lang)}"
                    f"{' ✓' if priority == 'plus' else ''}",
                    "compute:priority:plus",
                ),
            ],
            [(tr("compute.btn_cancel_task", lang), "compute:cancel")],
        ]
    )


def _task_card_keyboard(task_id: str, lang: str) -> InlineKeyboardMarkup:
    return _buttons(
        [
            [(tr("common.btn_check_status", lang), f"compute:status:{task_id}")],
            [(tr("compute.btn_new_task", lang), "compute:restart")],
            [(f"↩️ {tr('common.btn_back', lang)}", "dashboard:home")],
        ]
    )


async def _safe_edit_message_text(query: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return await query.edit_message_text(*args, **kwargs)
    except BadRequest as exc:
        if "message is not modified" in str(exc).lower():
            logger.info("bot_compute_edit_skipped reason=message_not_modified")
            return None
        raise


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
            "bot_compute_upload_ignored telegram_id=%s flow_id=%s reason=no_image",
            _telegram_id(update),
            _flow_id(context),
        )
        return None
    file_id, filename, content_type = attachment
    tg_file = await context.bot.get_file(file_id)
    content = bytes(await tg_file.download_as_bytearray())
    logger.info(
        "bot_compute_upload_start telegram_id=%s flow_id=%s filename=%s "
        "content_type=%s bytes=%s media_group_id=%s",
        _telegram_id(update),
        _flow_id(context),
        filename,
        content_type,
        len(content),
        _message_media_group_id(update) or "-",
    )
    data = await get_backend_client().upload_media(
        content=content,
        filename=filename,
        content_type=content_type,
    )
    file_ref = str(data.get("file_ref") or "")
    logger.info(
        "bot_compute_upload_done telegram_id=%s flow_id=%s filename=%s "
        "has_file_ref=%s",
        _telegram_id(update),
        _flow_id(context),
        filename,
        bool(file_ref),
    )
    return file_ref


async def compute_faces(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await get_user_lang_from_update(update)
    msg = update.effective_message
    if not msg:
        return ASK_FACES

    refs = _face_refs(context)
    if len(refs) >= _MAX_FACE_IMAGES:
        logger.info(
            "bot_compute_faces_full telegram_id=%s flow_id=%s count=%s",
            _telegram_id(update),
            _flow_id(context),
            len(refs),
        )
        await _reply_active_panel(
            msg,
            context,
            tr("compute.faces_full", lang),
            reply_markup=_faces_keyboard(lang, can_next=True),
        )
        return ASK_FACES
    _remember_face_media_group(update, context)

    try:
        file_ref = await _upload_image(update, context)
    except BackendAPIError as e:
        await _reply_backend_error(msg, lang, e)
        return ASK_FACES

    if not file_ref:
        await _reply_active_panel(
            msg,
            context,
            tr("compute.invalid_image", lang),
            reply_markup=_faces_keyboard(lang, can_next=bool(refs)),
        )
        return ASK_FACES

    refs.append(file_ref)
    context.user_data["face_images"] = refs[:_MAX_FACE_IMAGES]
    logger.info(
        "bot_compute_face_received telegram_id=%s flow_id=%s count=%s "
        "media_group_id=%s",
        _telegram_id(update),
        _flow_id(context),
        len(refs),
        _message_media_group_id(update) or "-",
    )
    await _reply_active_panel(
        msg,
        context,
        tr("compute.faces_received", lang, count=len(refs), max=_MAX_FACE_IMAGES),
        reply_markup=_faces_keyboard(lang, can_next=True),
    )
    return ASK_FACES


async def compute_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await get_user_lang_from_update(update)
    msg = update.effective_message
    if not msg:
        return ASK_TARGET
    if _is_from_face_media_group(update, context):
        logger.info(
            "bot_compute_target_ignored telegram_id=%s flow_id=%s "
            "reason=face_album_tail media_group_id=%s",
            _telegram_id(update),
            _flow_id(context),
            _message_media_group_id(update) or "-",
        )
        await _reply_active_panel(
            msg,
            context,
            tr("compute.face_album_tail_ignored", lang),
            reply_markup=_target_keyboard(lang),
        )
        return ASK_TARGET
    if context.user_data.get("target_image"):
        logger.info(
            "bot_compute_target_ignored telegram_id=%s flow_id=%s "
            "reason=target_already_set",
            _telegram_id(update),
            _flow_id(context),
        )
        await _reply_active_panel(
            msg,
            context,
            tr("compute.target_already_received", lang),
            reply_markup=_target_keyboard(lang),
        )
        return ASK_TARGET
    try:
        file_ref = await _upload_image(update, context)
    except BackendAPIError as e:
        await _reply_backend_error(msg, lang, e)
        return ASK_TARGET

    if not file_ref:
        await _reply_active_panel(
            msg,
            context,
            tr("compute.invalid_image", lang),
            reply_markup=_target_keyboard(lang),
        )
        return ASK_TARGET

    context.user_data["target_image"] = file_ref
    logger.info(
        "bot_compute_target_received telegram_id=%s flow_id=%s",
        _telegram_id(update),
        _flow_id(context),
    )
    await _reply_active_panel(
        msg,
        context,
        tr("compute.target_received", lang),
        reply_markup=_target_keyboard(lang),
    )
    return ASK_TARGET


async def compute_unexpected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    if msg:
        lang = await get_user_lang_from_update(update)
        await _reply_active_panel(
            msg,
            context,
            tr("compute.use_buttons", lang),
            reply_markup=_confirm_keyboard(context, lang),
        )
    return CONFIRM


async def compute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    lang = await get_user_lang_from_update(update)
    data = query.data or ""

    if data == "compute:cancel":
        logger.info(
            "bot_compute_cancel telegram_id=%s flow_id=%s source=callback",
            _telegram_id(update),
            _flow_id(context),
        )
        context.user_data.clear()
        await edit_to_dashboard_home(query, context, lang)
        return ConversationHandler.END

    if data == "compute:faces_next":
        if not _face_refs(context):
            logger.info(
                "bot_compute_next_blocked telegram_id=%s flow_id=%s "
                "reason=no_faces",
                _telegram_id(update),
                _flow_id(context),
            )
            await _edit_active_panel(
                query,
                context,
                tr("compute.need_faces", lang),
                reply_markup=_faces_keyboard(lang, can_next=False),
            )
            return ASK_FACES
        logger.info(
            "bot_compute_step telegram_id=%s flow_id=%s step=target faces=%s",
            _telegram_id(update),
            _flow_id(context),
            len(_face_refs(context)),
        )
        await _edit_active_panel(
            query,
            context,
            tr("compute.ask_target", lang),
            parse_mode="HTML",
            reply_markup=_target_keyboard(lang),
        )
        return ASK_TARGET

    if data == "compute:target_next":
        if not context.user_data.get("target_image"):
            logger.info(
                "bot_compute_next_blocked telegram_id=%s flow_id=%s "
                "reason=no_target",
                _telegram_id(update),
                _flow_id(context),
            )
            await _edit_active_panel(
                query,
                context,
                tr("compute.need_target", lang),
                reply_markup=_target_keyboard(lang),
            )
            return ASK_TARGET
        await _show_confirm(query, context, lang)
        return CONFIRM

    if data == "compute:toggle_restore":
        context.user_data["restore"] = not bool(context.user_data.get("restore", False))
        logger.info(
            "bot_compute_restore_toggle telegram_id=%s flow_id=%s restore=%s",
            _telegram_id(update),
            _flow_id(context),
            bool(context.user_data.get("restore", False)),
        )
        await _show_confirm(query, context, lang)
        return CONFIRM

    if data.startswith("compute:priority:"):
        priority = data.rsplit(":", 1)[-1]
        if priority in _PRIORITY_TYPES:
            context.user_data["compute_priority"] = priority
            logger.info(
                "bot_compute_priority_select telegram_id=%s flow_id=%s priority=%s",
                _telegram_id(update),
                _flow_id(context),
                priority,
            )
        await _show_confirm(query, context, lang)
        return CONFIRM

    if data == "compute:start":
        return await _start_task(query, context, lang)

    return CONFIRM


async def compute_global_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Conversation 结束后的任务卡片按钮。"""
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    lang = await get_user_lang_from_update(update)
    data = query.data or ""
    if data == "compute:restart":
        logger.info(
            "bot_compute_restart telegram_id=%s flow_id=%s",
            _telegram_id(update),
            _flow_id(context),
        )
        await _restart_from_query(query, context, lang)
        return
    if data.startswith("compute:status:"):
        task_id = data.rsplit(":", 1)[-1]
        try:
            logger.info(
                "bot_compute_status_refresh telegram_id=%s task_id=%s",
                update.effective_user.id,
                task_id,
            )
            task = await get_backend_client().get_task(
                UUID(task_id),
                update.effective_user.id,
            )
        except ValueError:
            await _safe_edit_message_text(query, tr("task.invalid_ref", lang))
            return
        except BackendAPIError as e:
            await _safe_edit_message_text(query, _task_error_text(lang, e))
            return
        await _safe_edit_message_text(
            query,
            render_task_status(task, lang),
            parse_mode="HTML",
            reply_markup=_task_card_keyboard(task_id, lang),
        )
        sent_tasks = set(context.user_data.get("compute_result_sent_tasks") or [])
        if task_id not in sent_tasks:
            sent = await send_task_result_images(
                getattr(query, "message", None),
                task,
                lang,
            )
            if sent:
                sent_tasks.add(task_id)
                context.user_data["compute_result_sent_tasks"] = sent_tasks
        return


async def compute_restart_entry(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    lang = await get_user_lang_from_update(update)
    await _restart_from_query(query, context, lang)
    return ASK_FACES


async def _restart_from_query(
    query: Any,
    context: ContextTypes.DEFAULT_TYPE,
    lang: str,
) -> None:
    context.user_data.clear()
    context.user_data["compute_flow_id"] = uuid4().hex
    context.user_data["compute_priority"] = _DEFAULT_PRIORITY
    context.user_data["restore"] = _DEFAULT_RESTORE
    context.user_data["face_images"] = []
    context.user_data["face_media_group_ids"] = set()
    await _edit_active_panel(
        query,
        context,
        tr("compute.ask_faces", lang),
        parse_mode="HTML",
        reply_markup=_faces_keyboard(lang, can_next=False),
    )


async def _show_confirm(
    query: Any,
    context: ContextTypes.DEFAULT_TYPE,
    lang: str,
) -> None:
    priority = str(context.user_data.get("compute_priority", _DEFAULT_PRIORITY))
    restore = bool(context.user_data.get("restore", _DEFAULT_RESTORE))
    await _edit_active_panel(
        query,
        context,
        tr(
            "compute.confirm",
            lang,
            faces=len(_face_refs(context)),
            restore=tr("compute.on" if restore else "compute.off", lang),
            priority=_priority_label(priority, lang),
            hold=str(_current_hold(context)),
        ),
        parse_mode="HTML",
        reply_markup=_confirm_keyboard(context, lang),
    )


async def _start_task(query: Any, context: ContextTypes.DEFAULT_TYPE, lang: str) -> int:
    if not query.message or not query.from_user:
        return ConversationHandler.END
    faces = _face_refs(context)
    target = str(context.user_data.get("target_image") or "")
    if not faces or not target:
        await _edit_active_panel(query, context, tr("compute.missing_inputs", lang))
        return ConversationHandler.END

    priority = str(context.user_data.get("compute_priority", _DEFAULT_PRIORITY))
    hold = _current_hold(context)
    restore = bool(context.user_data.get("restore", _DEFAULT_RESTORE))
    body = task_body_for_create(
        telegram_id=query.from_user.id,
        task_type=_TASK_TYPE,
        third_party_platform=_PLATFORM,
        priority_type=priority,
        input_payload={
            "face_images": faces,
            "target_image": target,
            "restore": restore,
        },
    )

    try:
        logger.info(
            "bot_compute_create_task_start telegram_id=%s flow_id=%s faces=%s "
            "priority=%s restore=%s hold=%s",
            query.from_user.id,
            _flow_id(context),
            len(faces),
            priority,
            restore,
            hold,
        )
        data = await get_backend_client().create_task(body)
    except BackendAPIError as e:
        logger.warning(
            "bot_compute_create_task_failed telegram_id=%s flow_id=%s "
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
        "bot_compute_create_task_done telegram_id=%s flow_id=%s task_id=%s "
        "status=%s priority=%s hold=%s",
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
            "compute.success",
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


def _task_error_text(lang: str, err: BackendAPIError) -> str:
    if err.http_status == 404:
        return tr("task.not_found", lang)
    if err.is_transport:
        return tr("errors.backend_transport", lang)
    if err.http_status in (401, 403):
        return tr("errors.backend_auth", lang)
    return tr("common.error", lang)


async def compute_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await get_user_lang_from_update(update)
    msg = update.effective_message
    if msg:
        logger.info(
            "bot_compute_cancel telegram_id=%s flow_id=%s source=command",
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


def get_compute_conversation_handler() -> ConversationHandler:
    image_filter = filters.PHOTO | filters.Document.IMAGE
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                compute_restart_entry,
                pattern=r"^(compute:restart|dashboard:compute)$",
            ),
        ],
        states={
            ASK_FACES: [
                MessageHandler(image_filter, compute_faces),
                CallbackQueryHandler(compute_callback, pattern=r"^compute:"),
            ],
            ASK_TARGET: [
                MessageHandler(image_filter, compute_target),
                CallbackQueryHandler(compute_callback, pattern=r"^compute:"),
            ],
            CONFIRM: [
                CallbackQueryHandler(compute_callback, pattern=r"^compute:"),
                MessageHandler(image_filter, compute_unexpected),
            ],
        },
        fallbacks=[CommandHandler("cancel", compute_cancel)],
        name="compute_create",
        allow_reentry=True,
    )
