#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""任务历史分页查询。"""

import math

from telegram import Update
from telegram.ext import ContextTypes

from frontend.bot.keyboards import pagination_keyboard
from frontend.core.utils import format_datetime, get_user_lang_from_update, tr
from frontend.integrations import BackendAPIError, get_backend_client

PER_PAGE = 5


def _task_type_label(task_type: str, lang: str) -> str:
    key = f"task_type.{task_type}"
    label = tr(key, lang)
    return task_type if label == key else label


async def task_history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """展示任务历史首页。"""
    await _show_task_history(update, page=1, edit=bool(update.callback_query))


async def task_history_page_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """处理任务历史分页 task_history_page:<n>。"""
    query = update.callback_query
    await query.answer()
    try:
        page = int((query.data or "").split(":")[-1])
    except (ValueError, IndexError):
        page = 1
    await _show_task_history(update, page=page, edit=True)


async def _show_task_history(
    update: Update,
    page: int = 1,
    edit: bool = False,
) -> None:
    if not update.effective_user:
        return

    lang = await get_user_lang_from_update(update)
    telegram_id = update.effective_user.id
    skip = max(0, (page - 1) * PER_PAGE)

    try:
        data = await get_backend_client().list_user_tasks(
            telegram_id,
            skip=skip,
            limit=PER_PAGE,
        )
    except BackendAPIError as e:
        if e.is_transport:
            text = tr("errors.backend_transport", lang)
        elif e.http_status in (401, 403):
            text = tr("errors.backend_auth", lang)
        else:
            text = tr("common.error", lang)
        await _send_or_edit(update, text, edit=edit)
        return

    total = int(data.get("total") or 0)
    tasks = list(data.get("tasks") or [])
    if total == 0:
        text = f"{tr('task_history.title', lang)}\n\n{tr('task_history.empty', lang)}"
        keyboard = pagination_keyboard(
            1,
            1,
            "task_history_page",
            lang,
            back_callback="dashboard:home" if edit else None,
        )
        await _send_or_edit(
            update,
            text,
            edit=edit,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return

    total_pages = max(1, math.ceil(total / PER_PAGE))
    display_page = max(1, min(page, total_pages))
    if display_page != page:
        data = await get_backend_client().list_user_tasks(
            telegram_id,
            skip=(display_page - 1) * PER_PAGE,
            limit=PER_PAGE,
        )
        tasks = list(data.get("tasks") or [])

    lines = [tr("task_history.title", lang), ""]
    for task in tasks:
        lines.append(
            tr(
                "task_history.entry",
                lang,
                code=str(task.get("task_code") or "-"),
                time=format_datetime(task.get("queued_at")),
                type=_task_type_label(str(task.get("task_type") or "-"), lang),
                status=str(task.get("status") or "-"),
            )
        )

    lines.append("")
    lines.append(
        tr("task_history.page", lang, current=display_page, total=total_pages)
    )
    keyboard = pagination_keyboard(
        display_page,
        total_pages,
        "task_history_page",
        lang,
        back_callback="dashboard:home" if edit else None,
    )
    await _send_or_edit(
        update,
        "\n".join(lines),
        edit=edit,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def _send_or_edit(
    update: Update,
    text: str,
    *,
    edit: bool,
    **kwargs,
) -> None:
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, **kwargs)
    elif update.effective_message:
        await update.effective_message.reply_text(text, **kwargs)
