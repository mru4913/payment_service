#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""算力任务入队：配置 `CELERY_BROKER_URL` 时经 Celery 发往 Redis（§7）。

Worker 处理完毕后务必将 `tasks` 标为终态，并调用
`backend.workers.settle_task_balance_hold_async`（或同步 `settle_task_balance_hold`）
以释放或 capture 预授权，避免长期占用 `balance_held`。
"""

import uuid

from ..globals import logger, settings
from .celery_tasks import CELERY_TASK_NAME


def enqueue_compute_task(task_id: uuid.UUID) -> None:
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
        return

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
