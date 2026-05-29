#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Batch terminal aggregation, packaging, and Telegram delivery."""

from __future__ import annotations

import io
import json
import tarfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from common.storage import resolve_file_ref
from common.task_refs import public_task_code
from common.task_results import extract_result_image_urls

from ..database.session import async_session_maker
from ..domain.batch_enums import BatchStatus
from ..globals import logger, settings
from ..services.batch_archives import result_archive_name
from ..services.batch_service import BatchService
from .celery_app import celery_app
from .telegram_notify import (
    send_batch_failed_message_to_user,
    send_batch_result_archives_to_user,
)


@dataclass(frozen=True, slots=True)
class _ArchiveEntry:
    relative_path: str
    content: bytes


async def batch_success_missing_result(
    *,
    task_id: uuid.UUID,
    result_payload: dict[str, Any] | None,
) -> bool:
    """Return True for a batch child that succeeded upstream without an image."""
    if extract_result_image_urls(result_payload):
        return False
    try:
        async with async_session_maker() as session:
            svc = BatchService(session)
            return await svc.is_batch_task(task_id)
    except Exception:
        logger.exception("batch_result_check_failed task_id=%s", task_id)
        return False


async def mark_batch_task_running(task_id: uuid.UUID) -> None:
    """Best-effort sync from child RH running state to parent batch status."""
    try:
        async with async_session_maker() as session:
            async with session.begin():
                svc = BatchService(session)
                marked = await svc.mark_task_running(task_id)
        if marked:
            logger.info("batch_task_running task_id=%s", task_id)
    except Exception:
        logger.exception("batch_task_running_failed task_id=%s", task_id)


def enqueue_package_batch_result(batch_id: uuid.UUID) -> bool:
    """Enqueue archive packaging on the maintenance queue."""
    if not settings.celery_broker_url:
        logger.warning(
            "batch_package_enqueue_skipped batch_id=%s reason=missing_broker",
            batch_id,
        )
        return False
    try:
        celery_app.send_task(
            "tasks.package_batch_result",
            args=[str(batch_id)],
            queue="maintenance",
        )
    except Exception:
        logger.exception("batch_package_enqueue_failed batch_id=%s", batch_id)
        return False
    logger.info("batch_package_enqueued batch_id=%s", batch_id)
    return True


async def handle_batch_task_terminal(
    *,
    task_id: uuid.UUID,
    terminal_status: str,
    result_payload: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> bool:
    """Return True when task belongs to a batch and single-task notify should stop."""
    try:
        async with async_session_maker() as session:
            async with session.begin():
                svc = BatchService(session)
                action = await svc.record_task_terminal(
                    task_id=task_id,
                    terminal_status=terminal_status,
                    result_payload=result_payload,
                    error_message=error_message,
                )
    except Exception:
        logger.exception(
            "batch_terminal_record_failed task_id=%s status=%s",
            task_id,
            terminal_status,
        )
        return False

    if not action.is_batch_task:
        return False
    if action.batch_id is None:
        return True
    if action.should_notify_failed:
        await _notify_all_failed(action.batch_id)
    if action.should_package:
        if not enqueue_package_batch_result(action.batch_id):
            logger.warning(
                "batch_package_inline_fallback batch_id=%s reason=enqueue_failed",
                action.batch_id,
            )
            await package_and_notify_batch(action.batch_id)
    return True


async def _notify_all_failed(batch_id: uuid.UUID) -> None:
    async with async_session_maker() as session:
        svc = BatchService(session)
        batch = await svc.batch_repo.get_by_batch_id(batch_id)
    if not batch:
        return
    await send_batch_failed_message_to_user(
        settings=settings,
        telegram_id=int(batch.telegram_id),
        batch_id=batch.batch_id,
        total_items=batch.total_items,
    )


async def package_and_notify_batch(batch_id: uuid.UUID) -> None:
    """Download successful child results, rebuild archive(s), and notify user."""
    claim_id = uuid.uuid4().hex
    paths: list[Path] = []
    stale_before = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        seconds=max(1, int(settings.batch_packaging_claim_timeout_sec))
    )
    async with async_session_maker() as session:
        async with session.begin():
            svc = BatchService(session)
            claimed = await svc.claim_packaging_batch(
                batch_id=batch_id,
                claim_id=claim_id,
                stale_before=stale_before,
            )
    if not claimed:
        logger.info(
            "batch_packaging_skip_claimed batch_id=%s claim_id=%s",
            batch_id,
            claim_id,
        )
        return

    async with async_session_maker() as session:
        svc = BatchService(session)
        batch = await svc.batch_repo.get_by_batch_id(batch_id)
        items = await svc.list_items(batch_id)

    if not batch:
        return
    if (
        batch.status
        in {
            BatchStatus.COMPLETED.value,
            BatchStatus.PARTIAL_FAILED.value,
            BatchStatus.FAILED.value,
        }
        and batch.result_archive_path
    ):
        logger.info(
            "batch_packaging_skip_final batch_id=%s status=%s",
            batch_id,
            batch.status,
        )
        return
    if batch.status != BatchStatus.PACKAGING.value:
        logger.info(
            "batch_packaging_skip_status batch_id=%s status=%s",
            batch_id,
            batch.status,
        )
        return
    try:
        async with async_session_maker() as session:
            async with session.begin():
                svc = BatchService(session)
                still_owner = await svc.refresh_packaging_claim(
                    batch_id=batch.batch_id,
                    claim_id=claim_id,
                )
        if not still_owner:
            logger.warning(
                "batch_packaging_skip_stale_before_build batch_id=%s claim_id=%s",
                batch.batch_id,
                claim_id,
            )
            return
        paths = await _build_result_archives(batch, items)
        async with async_session_maker() as session:
            async with session.begin():
                svc = BatchService(session)
                still_owner = await svc.refresh_packaging_claim(
                    batch_id=batch.batch_id,
                    claim_id=claim_id,
                )
        if not still_owner:
            logger.warning(
                "batch_packaging_skip_stale_before_send batch_id=%s claim_id=%s",
                batch.batch_id,
                claim_id,
            )
            _cleanup_paths(paths)
            return
        result_archive_path = "\n".join(str(path) for path in paths)
        async with async_session_maker() as session:
            async with session.begin():
                svc = BatchService(session)
                delivery_started = await svc.begin_delivery(
                    batch_id=batch.batch_id,
                    claim_id=claim_id,
                    result_archive_path=result_archive_path,
                )
        if not delivery_started:
            logger.warning(
                "batch_packaging_delivery_stale batch_id=%s claim_id=%s",
                batch.batch_id,
                claim_id,
            )
            _cleanup_paths(paths)
            return
    except Exception as exc:
        logger.exception("batch_packaging_failed batch_id=%s error=%s", batch_id, exc)
        failed = await _mark_packaging_failed(batch_id, claim_id, str(exc))
        if not failed:
            logger.warning(
                "batch_packaging_failed_stale batch_id=%s claim_id=%s",
                batch_id,
                claim_id,
            )
            return
        await send_batch_failed_message_to_user(
            settings=settings,
            telegram_id=int(batch.telegram_id),
            batch_id=batch.batch_id,
            total_items=batch.total_items,
            error_message="结果打包失败，请稍后联系人工处理。",
        )
        return

    try:
        sent = await send_batch_result_archives_to_user(
            settings=settings,
            telegram_id=int(batch.telegram_id),
            batch_id=batch.batch_id,
            total_items=batch.total_items,
            succeeded_items=batch.succeeded_items,
            failed_items=batch.failed_items,
            archive_paths=paths,
        )
        if not sent:
            raise RuntimeError("telegram document notification failed")
    except Exception as exc:
        logger.exception(
            "batch_delivery_failed batch_id=%s claim_id=%s error=%s",
            batch.batch_id,
            claim_id,
            exc,
        )
        failed = await _mark_delivery_failed(batch.batch_id, claim_id, str(exc))
        if failed:
            await send_batch_failed_message_to_user(
                settings=settings,
                telegram_id=int(batch.telegram_id),
                batch_id=batch.batch_id,
                total_items=batch.total_items,
                error_message="结果发送失败，请稍后联系人工处理。",
            )
        return

    try:
        async with async_session_maker() as session:
            async with session.begin():
                svc = BatchService(session)
                completed = await svc.complete_delivery(
                    batch_id=batch.batch_id,
                    claim_id=claim_id,
                )
        if not completed:
            logger.warning(
                "batch_delivery_complete_stale batch_id=%s claim_id=%s",
                batch.batch_id,
                claim_id,
            )
    except Exception as exc:
        logger.exception(
            "batch_delivery_complete_failed_after_send batch_id=%s claim_id=%s "
            "error=%s",
            batch.batch_id,
            claim_id,
            exc,
        )


async def _mark_packaging_failed(
    batch_id: uuid.UUID,
    claim_id: str,
    error_message: str,
) -> bool:
    async with async_session_maker() as session:
        async with session.begin():
            svc = BatchService(session)
            return await svc.mark_packaging_failed(
                batch_id=batch_id,
                claim_id=claim_id,
                error_message=error_message,
            )


async def _mark_delivery_failed(
    batch_id: uuid.UUID,
    claim_id: str,
    error_message: str,
) -> bool:
    async with async_session_maker() as session:
        async with session.begin():
            svc = BatchService(session)
            return await svc.mark_delivery_failed(
                batch_id=batch_id,
                claim_id=claim_id,
                error_message=error_message,
            )


def _cleanup_paths(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("batch_packaging_cleanup_failed path=%s", path)


async def _build_result_archives(batch: Any, items: list[Any]) -> list[Path]:
    manifest = _manifest(batch, items)
    entries: list[_ArchiveEntry] = []
    for item in items:
        if item.status != "succeeded" or not item.result_url:
            continue
        content, _fname, _ct = await resolve_file_ref(str(item.result_url))
        rel = item.result_relative_path or str(item.original_relative_path)
        entries.append(_ArchiveEntry(relative_path=rel, content=content))

    if not entries:
        raise RuntimeError("batch has no successful result images")

    result_dir = _result_dir(batch.batch_id)
    base_name = result_archive_name(
        str(batch.source_archive_name),
        str(batch.archive_format),
    )
    first = _write_archive(
        result_dir / base_name,
        str(batch.archive_format),
        entries,
        manifest,
    )
    max_bytes = int(settings.batch_telegram_document_max_bytes)
    if first.stat().st_size <= max_bytes:
        return [first]

    first.unlink(missing_ok=True)
    paths: list[Path] = []
    for index, entry in enumerate(entries, start=1):
        part_name = _part_archive_name(base_name, index)
        part = _write_archive(
            result_dir / part_name,
            str(batch.archive_format),
            [entry],
            manifest,
        )
        if part.stat().st_size > max_bytes:
            part.unlink(missing_ok=True)
            raise RuntimeError("单个结果文件超过 Telegram 发送限制")
        paths.append(part)
    return paths


def _result_dir(batch_id: uuid.UUID) -> Path:
    today = datetime.now(timezone.utc).date().isoformat()
    path = Path(settings.batch_result_dir) / today / str(batch_id)
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _manifest(batch: Any, items: list[Any]) -> dict[str, Any]:
    return {
        "batch_code": public_task_code(batch.batch_id),
        "task_type": batch.task_type,
        "status": batch.status,
        "total_items": batch.total_items,
        "succeeded_items": batch.succeeded_items,
        "failed_items": batch.failed_items,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": [
            {
                "input_path": item.original_relative_path,
                "output_path": item.result_relative_path,
                "status": item.status,
                "task_code": public_task_code(item.task_id),
                "error": item.error_message,
            }
            for item in items
        ],
    }


def _write_archive(
    path: Path,
    archive_format: str,
    entries: list[_ArchiveEntry],
    manifest: dict[str, Any],
) -> Path:
    manifest_bytes = json.dumps(
        manifest,
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    if archive_format == "zip":
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for entry in entries:
                zf.writestr(entry.relative_path, entry.content)
            zf.writestr("manifest.json", manifest_bytes)
        return path

    mode = "w:gz" if archive_format == "tar.gz" else "w"
    with tarfile.open(path, mode) as tf:
        for entry in entries:
            info = tarfile.TarInfo(entry.relative_path)
            info.size = len(entry.content)
            tf.addfile(info, io.BytesIO(entry.content))
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest_bytes)
        tf.addfile(info, io.BytesIO(manifest_bytes))
    return path


def _part_archive_name(base_name: str, index: int) -> str:
    if base_name.endswith(".tar.gz"):
        return f"{base_name[:-7]}_part_{index:03d}.tar.gz"
    stem = Path(base_name).stem
    suffix = "".join(Path(base_name).suffixes) or ".zip"
    return f"{stem}_part_{index:03d}{suffix}"
