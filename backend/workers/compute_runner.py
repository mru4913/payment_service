#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""算力任务 Worker 入口。

- ``third_party_platform == "runninghub"`` → 走 ``rh_pipeline``（真实调用 RH API）
- 其他 / 未识别平台 → 走 stub（直接推终态，开发联调用）

真实 Worker 应在写终态、``charged_amount`` 等字段之后，调用
``settle_task_balance_hold_async`` 释放或 capture 预授权。
"""

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from ..database.repositories import TaskRepository
from ..database.session import async_session_maker
from ..domain.task_enums import TaskStatus, ThirdPartyPlatform
from ..third_party.runninghub import RunningHubAPIError
from ..globals import logger
from .batch_results import handle_batch_task_terminal
from .rh_pipeline import run_runninghub_pipeline
from .slot_limiter import SlotBusyError
from .task_settlement import settle_task_balance_hold_async

Outcome = Literal["succeeded", "failed", "cancelled"]


async def _write_terminal_state(
    session: AsyncSession,
    task_id: uuid.UUID,
    outcome: Outcome,
    charged_amount: Decimal | None,
) -> bool:
    """写入终态。返回是否找到任务行（未找到则不应再结算预授权）。"""
    repo = TaskRepository(session)
    task = await repo.get_by_task_id(task_id)
    if not task:
        logger.warning("compute_runner: task not found task_id=%s", task_id)
        return False

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if outcome == "succeeded":
        payload = {
            "status": TaskStatus.SUCCEEDED.value,
            "completed_at": now,
            "charged_amount": (
                charged_amount if charged_amount is not None else Decimal("0")
            ),
        }
    elif outcome == "failed":
        payload = {
            "status": TaskStatus.FAILED.value,
            "completed_at": now,
            "error_code": "stub_failed",
            "error_message": "compute_runner stub failure",
        }
    else:
        payload = {
            "status": TaskStatus.CANCELLED.value,
            "completed_at": now,
        }

    await repo.update(task, payload)
    return True


async def promote_task_to_terminal_and_settle(
    task_id: uuid.UUID,
    *,
    outcome: Outcome = "succeeded",
    charged_amount: Decimal | None = None,
) -> None:
    """将任务标为终态（独立事务），再结算冻结（与业务 Worker 推荐顺序一致）。

    若数据库中尚无该 task_id 对应行，仅打日志，不调用结算（避免 task_not_found）。
    """
    async with async_session_maker() as session:
        async with session.begin():
            found = await _write_terminal_state(
                session, task_id, outcome, charged_amount
            )

    if found:
        await settle_task_balance_hold_async(task_id)


_TERMINAL_STATUSES = frozenset(
    {
        TaskStatus.SUCCEEDED.value,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
    }
)

_TASK_LOOKUP_RETRIES = 5
_TASK_LOOKUP_BASE_DELAY_S = 0.05


async def run_compute_task_for_worker(
    task_id: uuid.UUID,
    *,
    celery_task_id: str,
) -> None:
    """Worker 入口：终态仅补结算；否则按平台分发。"""
    task = None
    for attempt in range(_TASK_LOOKUP_RETRIES):
        async with async_session_maker() as session:
            async with session.begin():
                repo = TaskRepository(session)
                task = await repo.get_by_task_id(task_id)
        if task is not None:
            break
        delay = _TASK_LOOKUP_BASE_DELAY_S * (2 ** min(attempt, 4))
        await asyncio.sleep(delay)

    if task is None:
        logger.warning(
            "compute_runner: task not found after retries task_id=%s", task_id
        )
        return

    if task.status in _TERMINAL_STATUSES:
        await settle_task_balance_hold_async(task_id)
        return

    claim_id = celery_task_id or f"local-{task_id}"
    claimed = False
    platform: str = ""
    async with async_session_maker() as session:
        async with session.begin():
            repo = TaskRepository(session)
            claimed = await repo.claim_queued_task_for_worker(
                task_id,
                claim_id,
                datetime.now(timezone.utc).replace(tzinfo=None),
            )
            if claimed:
                task = await repo.get_by_task_id(task_id)
                if not task:
                    logger.warning("compute_runner: task vanished task_id=%s", task_id)
                    return
                platform = task.third_party_platform

    if not claimed:
        async with async_session_maker() as session:
            async with session.begin():
                repo = TaskRepository(session)
                current = await repo.get_by_task_id(task_id)
        if current and current.status in _TERMINAL_STATUSES:
            await settle_task_balance_hold_async(task_id)
        else:
            logger.info(
                "compute_runner: task already claimed or not queued task_id=%s "
                "celery_task_id=%s status=%s claimed_by=%s",
                task_id,
                claim_id,
                getattr(current, "status", "-"),
                getattr(current, "celery_task_id", "-"),
            )
        return

    try:
        await _dispatch(task_id, platform, claim_id)
    except SlotBusyError:
        async with async_session_maker() as session:
            async with session.begin():
                repo = TaskRepository(session)
                await repo.clear_queued_task_claim(task_id, claim_id)
        raise


async def _dispatch(
    task_id: uuid.UUID,
    platform: str,
    celery_task_id: str,
) -> None:
    """按平台分发到对应管线。"""
    if platform == ThirdPartyPlatform.RUNNINGHUB:
        try:
            await run_runninghub_pipeline(
                task_id,
                celery_task_id=celery_task_id,
            )
        except RunningHubAPIError:
            logger.exception(
                "compute_runner: rh_pipeline failed task_id=%s",
                task_id,
            )
            await settle_task_balance_hold_async(task_id)
            await handle_batch_task_terminal(
                task_id=task_id,
                terminal_status=TaskStatus.FAILED.value,
                error_message="RunningHub 创建任务失败",
            )
    else:
        await promote_task_to_terminal_and_settle(task_id)
