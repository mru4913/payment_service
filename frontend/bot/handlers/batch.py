#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Telegram batch remove-watermark workflow."""

from __future__ import annotations

import io
import math
import tarfile
import zipfile
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

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
from frontend.bot.keyboards import dashboard_keyboard, pagination_keyboard
from frontend.bot.navigation import edit_to_dashboard_home
from frontend.core.utils import format_datetime, get_user_lang_from_update, tr
from frontend.integrations import BackendAPIError, get_backend_client

ASK_ARCHIVE, CONFIRM = range(2)

_TASK_TYPE = "remove_watermark"
_DEFAULT_PRIORITY = "default"
_PRIORITY_TYPES = ("lite", "default", "plus")
_MAX_ITEMS = 20
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_SYSTEM_NAMES = {"__MACOSX", ".DS_Store", "Thumbs.db"}
_PER_PAGE = 5

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


def _archive_keyboard(lang: str) -> InlineKeyboardMarkup:
    return _buttons([[(tr("compute.btn_cancel_task", lang), "batch:cancel")]])


def _confirm_keyboard(
    context: ContextTypes.DEFAULT_TYPE,
    lang: str,
) -> InlineKeyboardMarkup:
    priority = str(context.user_data.get("batch_priority", _DEFAULT_PRIORITY))
    return _buttons(
        [
            [(tr("batch.btn_start", lang), "batch:start")],
            [
                (
                    f"{tr('compute.priority_lite', lang)}"
                    f"{' ✓' if priority == 'lite' else ''}",
                    "batch:priority:lite",
                ),
                (
                    f"{tr('compute.priority_default', lang)}"
                    f"{' ✓' if priority == 'default' else ''}",
                    "batch:priority:default",
                ),
                (
                    f"{tr('compute.priority_plus', lang)}"
                    f"{' ✓' if priority == 'plus' else ''}",
                    "batch:priority:plus",
                ),
            ],
            [(tr("compute.btn_cancel_task", lang), "batch:cancel")],
        ]
    )


def _batch_card_keyboard(batch_id: str, lang: str) -> InlineKeyboardMarkup:
    return _buttons(
        [
            [(tr("common.btn_check_status", lang), f"batch:status:{batch_id}")],
            [(tr("batch.btn_history", lang), "batch:history:1")],
            [(f"↩️ {tr('common.btn_back', lang)}", "dashboard:home")],
        ]
    )


def _archive_attachment(update: Update) -> tuple[str, str, str] | None:
    msg = update.effective_message
    if not msg or not msg.document:
        return None
    doc = msg.document
    filename = doc.file_name or "archive"
    lower = filename.lower()
    if not lower.endswith((".zip", ".tar", ".tar.gz", ".tgz")):
        return None
    return doc.file_id, filename, doc.mime_type or "application/octet-stream"


def _count_archive_images(content: bytes, filename: str) -> int:
    lower = filename.lower()
    if lower.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = [info.filename for info in zf.infolist() if not info.is_dir()]
    elif lower.endswith((".tar", ".tar.gz", ".tgz")):
        mode = "r:gz" if lower.endswith((".tar.gz", ".tgz")) else "r:"
        with tarfile.open(fileobj=io.BytesIO(content), mode=mode) as tf:
            names = [member.name for member in tf.getmembers() if member.isfile()]
    else:
        raise ValueError("unsupported")

    seen: set[str] = set()
    count = 0
    for name in names:
        safe = _safe_relative_path(name)
        if safe is None:
            continue
        if safe in seen:
            raise ValueError("duplicate")
        seen.add(safe)
        if PurePosixPath(safe).suffix.lower() in _IMAGE_SUFFIXES:
            count += 1
        if count > _MAX_ITEMS:
            raise ValueError("too_many")
    if count == 0:
        raise ValueError("no_images")
    return count


def _safe_relative_path(raw_name: str) -> str | None:
    name = raw_name.replace("\\", "/").strip()
    path = PurePosixPath(name)
    if not name or path.is_absolute() or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ValueError("unsafe_path")
    if any(part in _SYSTEM_NAMES or part.startswith(".") for part in path.parts):
        return None
    return str(path)


def _current_hold(context: ContextTypes.DEFAULT_TYPE) -> Decimal:
    priority = str(context.user_data.get("batch_priority", _DEFAULT_PRIORITY))
    count = int(context.user_data.get("batch_image_count") or 0)
    try:
        return estimate_hold_amount(_TASK_TYPE, priority) * Decimal(count)
    except ComputeCatalogError:
        logger.exception(
            "bot_batch_hold_estimate_failed task_type=%s priority=%s",
            _TASK_TYPE,
            priority,
        )
        return Decimal("0.216000") * Decimal(count)


async def batch_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    context.user_data.clear()
    context.user_data["batch_priority"] = _DEFAULT_PRIORITY
    context.user_data["batch_task_type"] = _TASK_TYPE
    lang = await get_user_lang_from_update(update)
    await query.edit_message_text(
        tr("batch.ask_archive", lang),
        reply_markup=_archive_keyboard(lang),
        parse_mode="HTML",
    )
    return ASK_ARCHIVE


async def batch_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    lang = await get_user_lang_from_update(update)
    data = query.data or ""

    if data == "batch:cancel":
        context.user_data.clear()
        await edit_to_dashboard_home(query, context, lang)
        return ConversationHandler.END

    if data.startswith("batch:priority:"):
        priority = data.rsplit(":", 1)[-1]
        if priority in _PRIORITY_TYPES:
            context.user_data["batch_priority"] = priority
        await _show_confirm(query, context, lang)
        return CONFIRM

    if data == "batch:start":
        return await _start_batch(query, context, lang)

    return ConversationHandler.END


async def batch_archive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await get_user_lang_from_update(update)
    msg = update.effective_message
    if not msg:
        return ASK_ARCHIVE
    attachment = _archive_attachment(update)
    if attachment is None:
        await msg.reply_text(
            tr("batch.invalid_archive", lang),
            reply_markup=_archive_keyboard(lang),
        )
        return ASK_ARCHIVE

    file_id, filename, content_type = attachment
    try:
        tg_file = await context.bot.get_file(file_id)
        content = bytes(await tg_file.download_as_bytearray())
        image_count = _count_archive_images(content, filename)
    except Exception:
        logger.exception("bot_batch_archive_parse_failed filename=%s", filename)
        await msg.reply_text(
            tr("batch.invalid_archive", lang),
            reply_markup=_archive_keyboard(lang),
        )
        return ASK_ARCHIVE

    context.user_data["batch_archive_content"] = content
    context.user_data["batch_archive_filename"] = filename
    context.user_data["batch_archive_content_type"] = content_type
    context.user_data["batch_image_count"] = image_count
    logger.info(
        "bot_batch_archive_received telegram_id=%s filename=%s bytes=%s images=%s",
        update.effective_user.id if update.effective_user else "-",
        filename,
        len(content),
        image_count,
    )
    await msg.reply_text(
        _confirm_text(context, lang),
        reply_markup=_confirm_keyboard(context, lang),
        parse_mode="HTML",
    )
    return CONFIRM


async def _show_confirm(
    query: Any,
    context: ContextTypes.DEFAULT_TYPE,
    lang: str,
) -> None:
    await query.edit_message_text(
        _confirm_text(context, lang),
        reply_markup=_confirm_keyboard(context, lang),
        parse_mode="HTML",
    )


def _confirm_text(context: ContextTypes.DEFAULT_TYPE, lang: str) -> str:
    priority = str(context.user_data.get("batch_priority", _DEFAULT_PRIORITY))
    return tr(
        "batch.confirm",
        lang,
        filename=str(context.user_data.get("batch_archive_filename") or "-"),
        count=int(context.user_data.get("batch_image_count") or 0),
        priority=_priority_label(priority, lang),
        hold=str(_current_hold(context)),
    )


async def _start_batch(
    query: Any,
    context: ContextTypes.DEFAULT_TYPE,
    lang: str,
) -> int:
    if not query.from_user:
        return ConversationHandler.END
    content = context.user_data.get("batch_archive_content")
    filename = str(context.user_data.get("batch_archive_filename") or "archive.zip")
    content_type = str(
        context.user_data.get("batch_archive_content_type")
        or "application/octet-stream"
    )
    if not isinstance(content, bytes):
        await query.edit_message_text(tr("batch.missing_archive", lang))
        context.user_data.clear()
        return ConversationHandler.END

    priority = str(context.user_data.get("batch_priority", _DEFAULT_PRIORITY))
    hold = _current_hold(context)
    try:
        data = await get_backend_client().create_remove_watermark_batch(
            telegram_id=query.from_user.id,
            priority_type=priority,
            content=content,
            filename=filename,
            content_type=content_type,
        )
    except BackendAPIError as e:
        await query.edit_message_text(_batch_error_text(lang, e))
        context.user_data.clear()
        return ConversationHandler.END

    batch_id = str(data.get("batch_id") or "")
    batch_code = str(data.get("batch_code") or public_task_code(batch_id))
    text = tr(
        "batch.success",
        lang,
        batch_code=batch_code,
        count=int(data.get("total_items") or 0),
        status=str(data.get("status") or ""),
        priority=_priority_label(priority, lang),
        hold=str(data.get("estimated_hold_amount") or hold),
    )
    await query.edit_message_text(
        text,
        reply_markup=_batch_card_keyboard(batch_id, lang),
        parse_mode="HTML",
    )
    context.user_data.clear()
    return ConversationHandler.END


async def batch_global_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    lang = await get_user_lang_from_update(update)
    data = query.data or ""
    if data.startswith("batch:status:"):
        raw = data.rsplit(":", 1)[-1]
        try:
            batch = await get_backend_client().get_batch(
                UUID(raw),
                update.effective_user.id,
            )
        except (ValueError, BackendAPIError):
            await query.edit_message_text(tr("batch.not_found", lang))
            return
        await query.edit_message_text(
            _render_batch_status(batch, lang),
            reply_markup=_batch_card_keyboard(raw, lang),
            parse_mode="HTML",
        )
        return
    if data.startswith("batch:history:"):
        try:
            page = int(data.rsplit(":", 1)[-1])
        except ValueError:
            page = 1
        await _show_batch_history(update, page=page)


async def _show_batch_history(update: Update, *, page: int) -> None:
    if not update.effective_user or not update.callback_query:
        return
    lang = await get_user_lang_from_update(update)
    skip = max(0, (page - 1) * _PER_PAGE)
    try:
        data = await get_backend_client().list_batches(
            update.effective_user.id,
            skip=skip,
            limit=_PER_PAGE,
        )
    except BackendAPIError:
        await update.callback_query.edit_message_text(tr("common.error", lang))
        return
    total = int(data.get("total") or 0)
    batches = list(data.get("batches") or [])
    total_pages = max(1, math.ceil(total / _PER_PAGE))
    page = max(1, min(page, total_pages))
    if total == 0:
        text = f"{tr('batch.history_title', lang)}\n\n{tr('batch.history_empty', lang)}"
    else:
        lines = [tr("batch.history_title", lang), ""]
        for batch in batches:
            lines.append(
                tr(
                    "batch.history_entry",
                    lang,
                    code=str(batch.get("batch_code") or "-"),
                    time=format_datetime(batch.get("created_at")),
                    total=int(batch.get("total_items") or 0),
                    success=int(batch.get("succeeded_items") or 0),
                    failed=int(batch.get("failed_items") or 0),
                    status=str(batch.get("status") or "-"),
                )
            )
        lines.append("")
        lines.append(tr("history.page", lang, current=page, total=total_pages))
        text = "\n".join(lines)
    await update.callback_query.edit_message_text(
        text,
        reply_markup=pagination_keyboard(
            page,
            total_pages,
            "batch:history",
            lang,
            back_callback="dashboard:home",
        ),
        parse_mode="HTML",
    )


def _render_batch_status(batch: dict[str, Any], lang: str) -> str:
    return tr(
        "batch.status",
        lang,
        batch_code=str(batch.get("batch_code") or "-"),
        status=str(batch.get("status") or "-"),
        total=int(batch.get("total_items") or 0),
        success=int(batch.get("succeeded_items") or 0),
        failed=int(batch.get("failed_items") or 0),
        created=format_datetime(batch.get("created_at")),
        completed=format_datetime(batch.get("completed_at")),
    )


def _batch_error_text(lang: str, err: BackendAPIError) -> str:
    if err.is_transport:
        return tr("errors.backend_transport", lang)
    if err.http_status in (401, 403):
        return tr("errors.backend_auth", lang)
    return err.message or tr("common.error", lang)


async def batch_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await get_user_lang_from_update(update)
    msg = update.effective_message
    context.user_data.clear()
    if msg and update.effective_user:
        await msg.reply_text(
            await dashboard_text_for_user(
                lang,
                update.effective_user.id,
                update.effective_user.first_name,
            ),
            reply_markup=dashboard_keyboard(lang),
            parse_mode="HTML",
        )
    return ConversationHandler.END


def get_batch_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(batch_entry, pattern=r"^dashboard:batch$"),
        ],
        states={
            ASK_ARCHIVE: [
                MessageHandler(filters.Document.ALL, batch_archive),
                CallbackQueryHandler(batch_callback, pattern=r"^batch:"),
            ],
            CONFIRM: [
                CallbackQueryHandler(batch_callback, pattern=r"^batch:"),
            ],
        },
        fallbacks=[CommandHandler("cancel", batch_cancel)],
        name="batch_remove_watermark",
        allow_reentry=True,
    )
