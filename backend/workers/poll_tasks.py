# -*- coding: utf-8 -*-
"""RunningHub 无 Webhook：轮询 ``query_task`` 收敛终态。"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..database.repositories import TaskRepository
from ..database.session import async_session_maker
from ..domain.task_enums import TaskStatus, ThirdPartyPlatform
from ..globals import logger, settings
from ..third_party.runninghub import (
    RunningHubAPIError,
    RunningHubClient,
    get_runninghub_client,
)
from .query_snapshot import build_query_snapshot, query_task_result_to_payload
from .slot_limiter import release_slot
from .task_settlement import settle_task_balance_hold_async
from .telegram_notify import (
    send_task_failed_message_to_user,
    send_task_success_images_to_user,
)
from .batch_results import batch_success_missing_result, handle_batch_task_terminal

POLL_TIMEOUT_ERROR_CODE = "poll_running_timeout"
_SUCCESS_STATUSES = {"SUCCESS", "SUCCEEDED", "COMPLETED", "COMPLETE", "FINISHED"}
_FAILED_STATUSES = {"FAILED", "FAIL", "ERROR", "CANCELLED", "CANCELED"}


@dataclass
class _PollBatchCounters:
    """单次 ``run_poll_terminal_batch`` tick 的计数（并发安全）。"""

    terminal_cas_hit: int = 0
    terminal_cas_miss: int = 0
    query_task_failures: int = 0
    still_in_progress: int = 0
    _lock: asyncio.Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_lock", asyncio.Lock())

    async def record_terminal_cas(self, hit: bool) -> None:
        async with self._lock:
            if hit:
                self.terminal_cas_hit += 1
            else:
                self.terminal_cas_miss += 1

    async def record_query_failure(self) -> None:
        async with self._lock:
            self.query_task_failures += 1

    async def record_still_in_progress(self) -> None:
        async with self._lock:
            self.still_in_progress += 1


def _anchor_time(task: Any) -> datetime:
    """时钟锚点：``started_at`` 优先，否则 ``queued_at``（均为 naive UTC）。"""
    if task.started_at is not None:
        return task.started_at
    return task.queued_at


async def _settle_and_release_slot(task_id: uuid.UUID, telegram_id: int) -> None:
    """终态 CAS 成功后结算并释槽。

    当前策略（与 Webhook 路径一致）：**settle 失败仍会 ``release_slot``**，避免用户
    永久占坑；对账依赖 ``settle_task_balance_hold_async`` 幂等与运维对日志告警
    （``poll_terminal: settle failed`` / ``release_slot failed``）。
    """
    settle_failed = False
    try:
        await settle_task_balance_hold_async(task_id)
    except Exception:
        settle_failed = True
        logger.exception(
            "poll_terminal: settle failed task_id=%s telegram_id=%s",
            task_id,
            telegram_id,
        )
    if settle_failed:
        logger.warning(
            "poll_terminal: settle failed but releasing slot anyway "
            "task_id=%s telegram_id=%s (see settlement policy in DEPLOYMENT.md)",
            task_id,
            telegram_id,
        )
    try:
        await release_slot(settings, telegram_id)
    except Exception:
        logger.exception(
            "poll_terminal: release_slot failed task_id=%s telegram_id=%s",
            task_id,
            telegram_id,
        )
    if not settle_failed:
        logger.info(
            "poll_terminal: finalized task_id=%s telegram_id=%s",
            task_id,
            telegram_id,
        )


async def _handle_timeout_discard(
    *,
    task_id: uuid.UUID,
    telegram_id: int,
    upstream_task_id: str,
    anchor: datetime,
    now: datetime,
    rh_client: RunningHubClient,
    stats: _PollBatchCounters,
) -> None:
    last_query = await build_query_snapshot(
        upstream_task_id, settings, rh_client=rh_client
    )
    err_msg = (
        f"running exceeded {settings.poll_max_running_sec}s "
        f"(upstream={upstream_task_id}, anchor={anchor.isoformat()})"
    )[:500]
    result_payload: dict[str, Any] = {
        "discard_reason": "max_running_exceeded",
        "poll_max_running_sec": settings.poll_max_running_sec,
        "last_query": last_query,
    }
    async with async_session_maker() as session:
        async with session.begin():
            repo = TaskRepository(session)
            ok = await repo.cas_transition_running_to_terminal(
                task_id,
                terminal_status=TaskStatus.FAILED.value,
                completed_at=now,
                result_payload=result_payload,
                error_code=POLL_TIMEOUT_ERROR_CODE,
                error_message=err_msg,
            )
    await stats.record_terminal_cas(ok)
    if ok:
        await _settle_and_release_slot(task_id, telegram_id)
        is_batch = await handle_batch_task_terminal(
            task_id=task_id,
            terminal_status=TaskStatus.FAILED.value,
            result_payload=result_payload,
            error_message=err_msg,
        )
        if is_batch:
            return
        await send_task_failed_message_to_user(
            settings=settings,
            telegram_id=telegram_id,
            task_id=task_id,
            error_message=err_msg,
        )


async def _handle_query_outcome(
    *,
    task_id: uuid.UUID,
    telegram_id: int,
    upstream_task_id: str,
    now: datetime,
    rh_client: RunningHubClient,
    stats: _PollBatchCounters,
) -> None:
    try:
        qr = await rh_client.query_task(upstream_task_id)
    except RunningHubAPIError:
        await stats.record_query_failure()
        logger.warning(
            "poll_terminal: query_task RH error task_id=%s upstream=%s",
            task_id,
            upstream_task_id,
            exc_info=True,
        )
        return
    except Exception:
        await stats.record_query_failure()
        logger.warning(
            "poll_terminal: query_task failed task_id=%s upstream=%s",
            task_id,
            upstream_task_id,
            exc_info=True,
        )
        return

    st = (qr.status or "").strip().upper()
    if st in _SUCCESS_STATUSES:
        query_payload = query_task_result_to_payload(qr)
        result_payload: dict[str, Any] = {"query": query_payload}
        terminal_status = TaskStatus.SUCCEEDED.value
        error_code: str | None = None
        error_message: str | None = None
        if await batch_success_missing_result(
            task_id=task_id,
            result_payload=result_payload,
        ):
            terminal_status = TaskStatus.FAILED.value
            error_code = "batch_no_result_image"
            error_message = "任务成功但未返回结果图片"
        async with async_session_maker() as session:
            async with session.begin():
                repo = TaskRepository(session)
                ok = await repo.cas_transition_running_to_terminal(
                    task_id,
                    terminal_status=terminal_status,
                    completed_at=now,
                    result_payload=result_payload,
                    error_code=error_code,
                    error_message=error_message,
                )
        await stats.record_terminal_cas(ok)
        if ok:
            await _settle_and_release_slot(task_id, telegram_id)
            is_batch = await handle_batch_task_terminal(
                task_id=task_id,
                terminal_status=terminal_status,
                result_payload=result_payload,
                error_message=error_message,
            )
            if is_batch:
                return
            if terminal_status != TaskStatus.SUCCEEDED.value:
                await send_task_failed_message_to_user(
                    settings=settings,
                    telegram_id=telegram_id,
                    task_id=task_id,
                    error_message=error_message,
                )
                return
            await send_task_success_images_to_user(
                settings=settings,
                telegram_id=telegram_id,
                task_id=task_id,
                result_payload=result_payload,
            )
        return

    if st in _FAILED_STATUSES:
        query_payload = query_task_result_to_payload(qr)
        result_payload = {"query": query_payload}
        err_code = (qr.error_code or "rh_query_failed")[:64]
        err_msg = (qr.error_message or "RunningHub query FAILED")[:500]
        async with async_session_maker() as session:
            async with session.begin():
                repo = TaskRepository(session)
                ok = await repo.cas_transition_running_to_terminal(
                    task_id,
                    terminal_status=TaskStatus.FAILED.value,
                    completed_at=now,
                    result_payload=result_payload,
                    error_code=err_code,
                    error_message=err_msg,
                )
        await stats.record_terminal_cas(ok)
        if ok:
            await _settle_and_release_slot(task_id, telegram_id)
            is_batch = await handle_batch_task_terminal(
                task_id=task_id,
                terminal_status=TaskStatus.FAILED.value,
                result_payload=result_payload,
                error_message=err_msg,
            )
            if is_batch:
                return
            await send_task_failed_message_to_user(
                settings=settings,
                telegram_id=telegram_id,
                task_id=task_id,
                error_message=err_msg,
            )
        return

    await stats.record_still_in_progress()
    logger.debug(
        "poll_terminal: still in progress task_id=%s upstream=%s status=%s",
        task_id,
        upstream_task_id,
        qr.status,
    )


async def _process_one_task_row(
    task: Any,
    *,
    rh_client: RunningHubClient,
    stats: _PollBatchCounters,
) -> None:
    if task.third_party_platform != ThirdPartyPlatform.RUNNINGHUB.value:
        return
    uid = task.upstream_task_id
    if not uid:
        return
    task_id: uuid.UUID = task.task_id
    telegram_id = int(task.telegram_id)
    anchor = _anchor_time(task)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    age_sec = (now - anchor).total_seconds()
    if age_sec >= settings.poll_max_running_sec:
        await _handle_timeout_discard(
            task_id=task_id,
            telegram_id=telegram_id,
            upstream_task_id=str(uid),
            anchor=anchor,
            now=now,
            rh_client=rh_client,
            stats=stats,
        )
        return
    await _handle_query_outcome(
        task_id=task_id,
        telegram_id=telegram_id,
        upstream_task_id=str(uid),
        now=now,
        rh_client=rh_client,
        stats=stats,
    )


def _warn_poll_broker_misconfig() -> None:
    if settings.poll_enabled and not settings.celery_broker_url:
        logger.warning(
            "poll_terminal: POLL_ENABLED=true but CELERY_BROKER_URL unset — "
            "Beat will not register poll_schedule; this worker tick still runs if "
            "invoked manually. Set CELERY_BROKER_URL and run celery_beat."
        )


async def run_poll_terminal_batch() -> None:
    """扫描一批 ``running`` 任务并 query / 超时 discard。"""
    if not settings.poll_enabled:
        logger.debug("poll_terminal: skipped (poll_enabled=false)")
        return
    if not settings.runninghub_api_key:
        logger.warning("poll_terminal: skipped (RUNNINGHUB_API_KEY empty)")
        return
    _warn_poll_broker_misconfig()

    batch = max(1, min(settings.poll_batch_size, 500))
    async with async_session_maker() as session:
        async with session.begin():
            repo = TaskRepository(session)
            rows = await repo.list_pollable_running_tasks(limit=batch)

    stats = _PollBatchCounters()
    t0 = time.perf_counter()
    conc = max(1, min(int(settings.poll_max_concurrent), 50))
    sem = asyncio.Semaphore(conc)

    rh = get_runninghub_client(settings)
    async with rh:

        async def _guarded_row(row: Any) -> None:
            async with sem:
                try:
                    await _process_one_task_row(row, rh_client=rh, stats=stats)
                except Exception:
                    logger.exception(
                        "poll_terminal: unexpected error task_id=%s",
                        getattr(row, "task_id", "?"),
                    )

        await asyncio.gather(*(_guarded_row(r) for r in rows))

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    logger.info(
        "poll_terminal: tick batch=%s elapsed_ms=%s concurrent=%s "
        "terminal_cas_hit=%s terminal_cas_miss=%s "
        "query_failures=%s still_in_progress=%s",
        len(rows),
        elapsed_ms,
        conc,
        stats.terminal_cas_hit,
        stats.terminal_cas_miss,
        stats.query_task_failures,
        stats.still_in_progress,
    )
