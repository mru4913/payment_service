#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""/task — 任务历史；/task <task_code> 查询单个任务。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from telegram import Update
from telegram.error import TimedOut
from telegram.ext import ContextTypes

from common.task_refs import normalize_task_ref, public_task_code
from common.logger import get_logger
from frontend.bot.handlers.task_history import task_history_handler
from frontend.core.utils import get_user_lang_from_update, tr, format_datetime
from frontend.integrations import BackendAPIError, get_backend_client

logger = get_logger("frontend_bot")


def _parse_dt(value: object) -> str:
    if value is None:
        return "-"
    s = value if isinstance(value, str) else str(value)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return format_datetime(dt.replace(tzinfo=None))
    except (ValueError, TypeError):
        return s


def render_task_status(data: dict, lang: str) -> str:
    """将任务详情渲染成 Bot 可发送的 HTML 文本。"""
    task_code = str(
        data.get("task_code") or public_task_code(str(data.get("task_id", "")))
    )
    lines = [
        tr("task.title", lang),
        "",
        tr("task.code", lang, code=task_code),
        tr("task.status", lang, status=str(data.get("status", ""))),
        tr("task.queued_at", lang, t=_parse_dt(data.get("queued_at"))),
        tr("task.started_at", lang, t=_parse_dt(data.get("started_at"))),
        tr("task.completed_at", lang, t=_parse_dt(data.get("completed_at"))),
    ]
    err = data.get("error_message")
    if err:
        lines.append(tr("task.error", lang, msg=err))
    return "\n".join(lines)


def result_image_urls(data: dict) -> list[str]:
    """返回任务结果图 URL，保持顺序并去重。"""
    raw = data.get("result_images")
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    urls: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        url = item.strip()
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


async def send_task_result_images(message: Any, data: dict, lang: str) -> bool:
    """任务成功时把结果图发给用户；失败时退化为文本链接。"""
    if not message or str(data.get("status", "")).lower() != "succeeded":
        return False
    urls = result_image_urls(data)
    if not urls:
        return False

    task_code = str(
        data.get("task_code") or public_task_code(str(data.get("task_id", "")))
    )
    sent_any = False
    for index, url in enumerate(urls[:4]):
        caption = (
            tr("task.result_caption", lang, code=task_code)
            if index == 0
            else None
        )
        try:
            await message.reply_photo(
                photo=url,
                caption=caption,
                parse_mode="HTML" if caption else None,
            )
            sent_any = True
        except TimedOut as exc:
            logger.warning(
                "bot_task_result_photo_timeout task_code=%s url=%s error=%s",
                task_code,
                url,
                exc,
            )
            sent_any = True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "bot_task_result_photo_failed task_code=%s url=%s error=%s",
                task_code,
                url,
                exc,
            )
            await message.reply_text(
                tr("task.result_link", lang, code=task_code, url=url),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            sent_any = True
    return sent_any


async def task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /task 或 /task <task_id/task_code>。"""
    msg = update.effective_message
    if not msg or not update.effective_user:
        return

    lang = await get_user_lang_from_update(update)
    if not context.args:
        await task_history_handler(update, context)
        return

    raw = normalize_task_ref(context.args[0])
    client = get_backend_client()
    try:
        if len(raw) == 32:
            task_id = UUID(raw)
            data = await client.get_task(task_id, update.effective_user.id)
        else:
            data = await client.get_task_by_ref(raw, update.effective_user.id)
    except ValueError:
        await msg.reply_text(tr("task.invalid_ref", lang))
        return
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

    await msg.reply_text(render_task_status(data, lang), parse_mode="HTML")
    await send_task_result_images(msg, data, lang)
