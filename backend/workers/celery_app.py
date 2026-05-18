#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Celery 应用实例（Broker 默认 Redis）。"""

import logging
from datetime import timedelta

from celery import Celery

from ..config import Settings

_log = logging.getLogger(__name__)
_settings = Settings()

if _settings.poll_enabled and not _settings.celery_broker_url:
    _log.warning(
        "POLL_ENABLED=true but CELERY_BROKER_URL is unset: Celery Beat will not "
        "register poll_schedule (tasks.poll_terminal). Set CELERY_BROKER_URL and "
        "run celery_beat plus worker_poll (maintenance queue). Worker broker still "
        "falls back to redis://127.0.0.1:6379/0 when unset."
    )


def _broker_url() -> str:
    if _settings.celery_broker_url:
        return _settings.celery_broker_url
    # 本地/容器内 Worker 未显式配置时仍可启动（Compose 应注入 CELERY_BROKER_URL）
    return "redis://127.0.0.1:6379/0"


celery_app = Celery(
    "eshow",
    broker=_broker_url(),
    include=["backend.workers.celery_tasks"],
)

if _settings.celery_result_backend:
    celery_app.conf.result_backend = _settings.celery_result_backend

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_default_queue="compute",
)
celery_app.conf.task_routes = {
    "tasks.execute_compute": {"queue": "compute"},
    "tasks.poll_terminal": {"queue": "maintenance"},
}

_beat_schedule: dict = {}
if _settings.poll_enabled and _settings.celery_broker_url:
    _beat_schedule["poll_schedule"] = {
        "task": "tasks.poll_terminal",
        "schedule": timedelta(seconds=max(5, int(_settings.poll_interval_sec))),
    }
celery_app.conf.beat_schedule = _beat_schedule
