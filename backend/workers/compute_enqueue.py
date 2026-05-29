#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""算力任务入队：配置 `CELERY_BROKER_URL` 时经 Celery 发往 Redis（§7）。

Worker 处理完毕后务必将 `tasks` 标为终态，并调用
`backend.workers.settle_task_balance_hold_async`（或同步 `settle_task_balance_hold`）
以释放或 capture 预授权，避免长期占用 `balance_held`。
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..database.repositories import TaskRepository
from ..database.session import async_session_maker
from ..domain.task_enums import TaskStatus
from ..globals import logger, settings
from .celery_tasks import CELERY_TASK_NAME


@dataclass(slots=True)
class ComputeRequeueStats:
    """One requeue tick summary."""

    scanned: int = 0
    enqueued: int = 0
    failed: int = 0
    skipped: int = 0


def enqueue_compute_task(task_id: uuid.UUID) -> bool:
    """投递异步执行：有 broker 时 `send_task`；否则仅日志（本地未起 Redis 时）。

    日志约定（便于检索）：``compute_task_enqueue_*``，含 ``task_id``、``reason`` /
    ``broker_configured``；入队失败时 ``compute_task_enqueue_failed`` 带异常栈。
    """
    broker_ok = bool(settings.celery_broker_url)
    logger.info(
        "compute_task_enqueue_start task_id=%s broker_configured=%s",
        task_id,
        broker_ok,
    )
    if not broker_ok:
        logger.warning(
            "compute_task_enqueue_skipped task_id=%s reason=no_broker "
            "hint=set_CELERY_BROKER_URL (no broker means no Celery queue and "
            "slot limiter has no Redis URL to fall back to)",
            task_id,
        )
        return False

    from .celery_app import celery_app  # noqa: PLC0415 — 仅在有 broker 时加载 Celery，缩短 API 冷启动

    try:
        celery_app.send_task(
            CELERY_TASK_NAME,
            args=[str(task_id)],
            queue="compute",
        )
    except Exception:
        logger.exception(
            "compute_task_enqueue_failed task_id=%s queue=compute task_name=%s",
            task_id,
            CELERY_TASK_NAME,
        )
        return False
    logger.info(
        "compute_task_enqueue_done task_id=%s queue=compute task_name=%s",
        task_id,
        CELERY_TASK_NAME,
    )
    return True


def _enqueue_cutoff(now: datetime) -> datetime:
    return now - timedelta(seconds=max(1, int(settings.compute_requeue_min_age_sec)))


def _claim_stale_before(now: datetime) -> datetime:
    return now - timedelta(
        seconds=max(1, int(settings.compute_worker_claim_stale_sec))
    )


async def claim_enqueue_attempt(task_id: uuid.UUID, *, cutoff: datetime) -> bool:
    """Persist enqueue attempt metadata before sending a Celery message."""
    attempted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        async with async_session_maker() as session:
            async with session.begin():
                repo = TaskRepository(session)
                claimed = await repo.claim_enqueue_attempt(
                    task_id,
                    cutoff=cutoff,
                    attempted_at=attempted_at,
                )
        if not claimed:
            logger.warning(
                "compute_task_enqueue_attempt_claim_miss task_id=%s cutoff=%s",
                task_id,
                cutoff.isoformat(),
            )
            return False
    except Exception:
        logger.exception(
            "compute_task_enqueue_attempt_claim_failed task_id=%s",
            task_id,
        )
        return False
    return True


async def enqueue_compute_task_with_record(task_id: uuid.UUID) -> bool:
    """Atomically claim an enqueue attempt, then try to enqueue a compute task."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if not await claim_enqueue_attempt(task_id, cutoff=_enqueue_cutoff(now)):
        return False
    return enqueue_compute_task(task_id)


async def run_requeue_queued_compute_tasks() -> ComputeRequeueStats:
    """Re-enqueue old queued tasks that were not claimed by any worker."""
    stats = ComputeRequeueStats()
    if not settings.compute_requeue_enabled:
        logger.debug("compute_requeue: skipped (compute_requeue_enabled=false)")
        return stats
    if not settings.celery_broker_url:
        logger.warning("compute_requeue: skipped (CELERY_BROKER_URL empty)")
        return stats

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = _enqueue_cutoff(now)
    claim_stale_before = _claim_stale_before(now)
    limit = max(1, min(int(settings.compute_requeue_batch_size), 1000))
    async with async_session_maker() as session:
        async with session.begin():
            repo = TaskRepository(session)
            rows = await repo.list_requeue_candidate_tasks(
                cutoff=cutoff,
                claim_stale_before=claim_stale_before,
                limit=limit,
            )

    for task in rows:
        if task.status != TaskStatus.QUEUED.value:
            stats.skipped += 1
            continue
        stats.scanned += 1
        if task.celery_task_id:
            async with async_session_maker() as session:
                async with session.begin():
                    repo = TaskRepository(session)
                    cleared = await repo.clear_stale_queued_task_claim(
                        task.task_id,
                        stale_before=claim_stale_before,
                    )
            if not cleared:
                stats.skipped += 1
                continue
            logger.warning(
                "compute_requeue: cleared_stale_worker_claim task_id=%s "
                "claimed_by=%s claim_stale_before=%s",
                task.task_id,
                task.celery_task_id,
                claim_stale_before.isoformat(),
            )
        if not await claim_enqueue_attempt(task.task_id, cutoff=cutoff):
            stats.skipped += 1
            continue
        ok = enqueue_compute_task(task.task_id)
        if ok:
            stats.enqueued += 1
        else:
            stats.failed += 1

    logger.info(
        "compute_requeue: tick scanned=%s enqueued=%s failed=%s skipped=%s cutoff=%s",
        stats.scanned,
        stats.enqueued,
        stats.failed,
        stats.skipped,
        cutoff.isoformat(),
    )
    return stats
