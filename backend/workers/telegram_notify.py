# -*- coding: utf-8 -*-
"""Worker 侧 Telegram 结果通知。"""

from __future__ import annotations

from typing import Any
from uuid import UUID
from pathlib import Path

import httpx

from common.task_refs import public_task_code
from common.task_results import extract_result_image_urls

from ..config import Settings
from ..globals import logger


def _telegram_api_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


async def _post_telegram(
    client: httpx.AsyncClient,
    token: str,
    method: str,
    payload: dict[str, Any],
) -> None:
    resp = await client.post(_telegram_api_url(token, method), json=payload)
    resp.raise_for_status()
    body = resp.json()
    if isinstance(body, dict) and body.get("ok") is False:
        raise RuntimeError(str(body.get("description") or "telegram api error"))


async def _post_telegram_multipart(
    client: httpx.AsyncClient,
    token: str,
    method: str,
    *,
    data: dict[str, Any],
    files: dict[str, Any],
) -> None:
    resp = await client.post(
        _telegram_api_url(token, method),
        data=data,
        files=files,
    )
    resp.raise_for_status()
    body = resp.json()
    if isinstance(body, dict) and body.get("ok") is False:
        raise RuntimeError(str(body.get("description") or "telegram api error"))


async def send_task_success_images_to_user(
    *,
    settings: Settings,
    telegram_id: int,
    task_id: UUID,
    result_payload: dict[str, Any] | None,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """任务成功后主动把结果图片发给用户。

    返回 ``True`` 表示至少发送了一条 photo 或 fallback link。
    """
    token = settings.telegram_bot_token
    if not token:
        logger.info(
            "task_result_notify_skipped task_id=%s telegram_id=%s reason=no_bot_token",
            task_id,
            telegram_id,
        )
        return False

    urls = extract_result_image_urls(result_payload)
    if not urls:
        logger.info(
            "task_result_notify_skipped task_id=%s telegram_id=%s reason=no_images",
            task_id,
            telegram_id,
        )
        return False

    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=15)
    task_code = public_task_code(task_id)
    sent_any = False
    try:
        for index, url in enumerate(urls[:4]):
            payload: dict[str, Any] = {
                "chat_id": telegram_id,
                "photo": url,
            }
            if index == 0:
                payload["caption"] = (
                    f"✅ 任务 <code>{task_code}</code> 已完成，结果如下。"
                )
                payload["parse_mode"] = "HTML"
            try:
                await _post_telegram(http_client, token, "sendPhoto", payload)
            except httpx.TimeoutException as exc:
                logger.warning(
                    "task_result_photo_notify_timeout task_id=%s telegram_id=%s "
                    "url=%s error=%s",
                    task_id,
                    telegram_id,
                    url,
                    exc,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "task_result_photo_notify_failed task_id=%s telegram_id=%s "
                    "url=%s error=%s",
                    task_id,
                    telegram_id,
                    url,
                    exc,
                )
                await _post_telegram(
                    http_client,
                    token,
                    "sendMessage",
                    {
                        "chat_id": telegram_id,
                        "text": f"✅ 任务 <code>{task_code}</code> 已完成：{url}",
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )
            sent_any = True
    finally:
        if owns_client:
            await http_client.aclose()

    if sent_any:
        logger.info(
            "task_result_notify_sent task_id=%s telegram_id=%s images=%s",
            task_id,
            telegram_id,
            min(len(urls), 4),
        )
    return sent_any


async def send_batch_result_archives_to_user(
    *,
    settings: Settings,
    telegram_id: int,
    batch_id: UUID,
    total_items: int,
    succeeded_items: int,
    failed_items: int,
    archive_paths: list[Path],
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Send completed batch result archive(s) as Telegram documents."""
    token = settings.telegram_bot_token
    if not token:
        logger.info(
            "batch_result_notify_skipped batch_id=%s telegram_id=%s "
            "reason=no_bot_token",
            batch_id,
            telegram_id,
        )
        return False
    if not archive_paths:
        return False

    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=60)
    batch_code = public_task_code(batch_id)
    sent_any = False
    try:
        for index, path in enumerate(archive_paths):
            caption = None
            if index == 0:
                if failed_items:
                    caption = (
                        f"📦 批量任务 <code>{batch_code}</code> 已完成。\n"
                        f"成功：{succeeded_items}/{total_items}，失败：{failed_items}。\n"
                        "失败明细见压缩包内 manifest.json。"
                    )
                else:
                    caption = (
                        f"📦 批量任务 <code>{batch_code}</code> 已完成。\n"
                        f"成功：{succeeded_items}/{total_items}。"
                    )
            data: dict[str, Any] = {"chat_id": telegram_id}
            if caption:
                data["caption"] = caption
                data["parse_mode"] = "HTML"
            files = {
                "document": (
                    path.name,
                    path.read_bytes(),
                    _archive_content_type(path),
                )
            }
            await _post_telegram_multipart(
                http_client,
                token,
                "sendDocument",
                data=data,
                files=files,
            )
            sent_any = True
    finally:
        if owns_client:
            await http_client.aclose()

    if sent_any:
        logger.info(
            "batch_result_notify_sent batch_id=%s telegram_id=%s archives=%s",
            batch_id,
            telegram_id,
            len(archive_paths),
        )
    return sent_any


async def send_batch_failed_message_to_user(
    *,
    settings: Settings,
    telegram_id: int,
    batch_id: UUID,
    total_items: int,
    error_message: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Notify user that a batch could not produce a result archive."""
    token = settings.telegram_bot_token
    if not token:
        logger.info(
            "batch_failed_notify_skipped batch_id=%s telegram_id=%s "
            "reason=no_bot_token",
            batch_id,
            telegram_id,
        )
        return False

    batch_code = public_task_code(batch_id)
    text = (
        f"❌ 批量任务 <code>{batch_code}</code> 处理失败。\n\n"
        f"图片数量：{total_items}\n"
        "失败任务不会扣费，预授权冻结会自动释放。"
    )
    if error_message:
        text += f"\n\n原因：{error_message[:300]}"

    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=15)
    try:
        await _post_telegram(
            http_client,
            token,
            "sendMessage",
            {
                "chat_id": telegram_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "batch_failed_notify_failed batch_id=%s telegram_id=%s error=%s",
            batch_id,
            telegram_id,
            exc,
        )
        return False
    finally:
        if owns_client:
            await http_client.aclose()

    logger.info(
        "batch_failed_notify_sent batch_id=%s telegram_id=%s",
        batch_id,
        telegram_id,
    )
    return True


def _archive_content_type(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".zip"):
        return "application/zip"
    if name.endswith(".tar.gz"):
        return "application/gzip"
    if name.endswith(".tar"):
        return "application/x-tar"
    return "application/octet-stream"


async def send_task_failed_message_to_user(
    *,
    settings: Settings,
    telegram_id: int,
    task_id: UUID,
    error_message: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """任务失败后主动通知用户；失败任务不扣费，冻结会在结算中释放。"""
    token = settings.telegram_bot_token
    if not token:
        logger.info(
            "task_failed_notify_skipped task_id=%s telegram_id=%s reason=no_bot_token",
            task_id,
            telegram_id,
        )
        return False

    task_code = public_task_code(task_id)
    reason = (error_message or "").strip()
    text = (
        f"❌ 任务 <code>{task_code}</code> 生成失败。\n\n"
        "本次任务不会扣费，预授权冻结会自动释放。"
    )
    if reason:
        text += f"\n\n原因：{reason[:300]}"

    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=15)
    try:
        await _post_telegram(
            http_client,
            token,
            "sendMessage",
            {
                "chat_id": telegram_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "task_failed_notify_failed task_id=%s telegram_id=%s error=%s",
            task_id,
            telegram_id,
            exc,
        )
        return False
    finally:
        if owns_client:
            await http_client.aclose()

    logger.info(
        "task_failed_notify_sent task_id=%s telegram_id=%s",
        task_id,
        telegram_id,
    )
    return True
