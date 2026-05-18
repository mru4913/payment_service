#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""/task <uuid> — 经 HTTP 查询任务状态。"""

from datetime import datetime
from uuid import UUID

from telegram import Update
from telegram.ext import ContextTypes

from frontend.core.utils import get_user_lang_from_update, tr, format_datetime
from frontend.integrations import BackendAPIError, get_backend_client


def _parse_dt(value: object) -> str:
    if value is None:
        return "-"
    s = value if isinstance(value, str) else str(value)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return format_datetime(dt.replace(tzinfo=None))
    except (ValueError, TypeError):
        return s


async def task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /task <task_id>。"""
    msg = update.effective_message
    if not msg or not update.effective_user:
        return

    lang = await get_user_lang_from_update(update)
    if not context.args:
        await msg.reply_text(tr("task.usage", lang))
        return

    raw = context.args[0].strip()
    try:
        task_id = UUID(raw)
    except ValueError:
        await msg.reply_text(tr("task.invalid_uuid", lang))
        return

    telegram_id = update.effective_user.id
    client = get_backend_client()

    try:
        data = await client.get_task(task_id, telegram_id)
    except BackendAPIError as e:
        if e.http_status == 404:
            await msg.reply_text(tr("task.not_found", lang))
            return
        if e.is_transport:
            await msg.reply_text(tr("errors.backend_transport", lang))
            return
        if e.http_status in (401, 403):
            await msg.reply_text(tr("errors.backend_auth", lang))
            return
        await msg.reply_text(tr("common.error", lang))
        return

    lines = [
        tr("task.title", lang),
        "",
        tr("task.status", lang, status=str(data.get("status", ""))),
        tr("task.queued_at", lang, t=_parse_dt(data.get("queued_at"))),
        tr("task.started_at", lang, t=_parse_dt(data.get("started_at"))),
        tr("task.completed_at", lang, t=_parse_dt(data.get("completed_at"))),
    ]
    up = data.get("upstream_task_id")
    if up:
        lines.append(tr("task.upstream", lang, id=up))
    err = data.get("error_message")
    if err:
        lines.append(tr("task.error", lang, msg=err))

    await msg.reply_text("\n".join(lines), parse_mode="HTML")
