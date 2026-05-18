#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Celery 任务定义"""

from __future__ import annotations

import asyncio
import uuid

from ..globals import logger
from .celery_app import celery_app
from .compute_runner import run_compute_task_for_worker
from .poll_tasks import run_poll_terminal_batch
from .slot_limiter import SlotBusyError

CELERY_TASK_NAME = "tasks.execute_compute"
POLL_TERMINAL_TASK_NAME = "tasks.poll_terminal"


@celery_app.task(bind=True, name=CELERY_TASK_NAME)
def execute_compute_task(self, task_id_str: str) -> None:
    """消费算力任务：幂等检查后按平台分发（RunningHub 管线 / stub）。"""
    task_id = uuid.UUID(task_id_str)
    celery_id = getattr(self.request, "id", None) or ""
    logger.info(
        "compute_worker_received task_id=%s celery_request_id=%s",
        task_id_str,
        celery_id,
    )
    try:
        asyncio.run(run_compute_task_for_worker(task_id, celery_task_id=celery_id))
    except SlotBusyError as exc:
        logger.info(
            "compute_task_slot_busy task_id=%s retries=%s",
            task_id_str,
            getattr(self.request, "retries", 0),
        )
        raise self.retry(exc=exc, countdown=2, max_retries=120) from exc


@celery_app.task(name=POLL_TERMINAL_TASK_NAME)
def poll_terminal_task() -> None:
    """Beat：扫 running+upstream，query RH 或超时 discard。"""
    asyncio.run(run_poll_terminal_batch())
