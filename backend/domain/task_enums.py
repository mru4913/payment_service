#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
任务相关枚举
"""

from enum import StrEnum


class TaskStatus(StrEnum):
    """tasks.status — 与 `backend/database/models/task.py` 注释一致。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskBalanceHoldStatus(StrEnum):
    """task_balance_holds.status — 与 `task_balance_hold` 模型注释一致。"""

    ACTIVE = "active"
    RELEASED = "released"
    CAPTURED = "captured"


class ThirdPartyPlatform(StrEnum):
    """第三方算力平台编码；MVP 至少支持 RunningHub。"""

    RUNNINGHUB = "runninghub"


class PriorityType(StrEnum):
    """算力档位；Worker 映射上游 instanceType 等。"""

    LITE = "lite"
    DEFAULT = "default"
    PLUS = "plus"
