#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
算力任务 API 契约（OpenAPI）— MVP 草图，与 `Task` 模型及业务设计 §5.2 / §8 对齐。
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ...domain.task_enums import PriorityType, TaskStatus, ThirdPartyPlatform


class CreateTaskRequest(BaseModel):
    """发起任务：结构化入参 + 可选说明与幂等键。"""

    model_config = ConfigDict(extra="forbid")

    telegram_id: int = Field(
        ...,
        description="用户 Telegram ID（关联 users.telegram_id）",
    )
    task_type: str = Field(
        ...,
        max_length=64,
        description="任务类型键（同 workflow_recipes），决定 input_payload 含义",
    )
    third_party_platform: ThirdPartyPlatform = Field(
        ...,
        description="第三方平台编码",
    )
    priority_type: PriorityType = Field(
        ...,
        description="算力档位，映射上游 instanceType",
    )
    input_payload: dict[str, Any] = Field(
        ...,
        description="与 task_type 绑定的 JSON（如 workflow_id、资源引用等）",
    )
    task_description: str | None = Field(
        default=None,
        description="展示用短说明",
    )
    idempotency_key: str | None = Field(
        default=None,
        max_length=64,
        description="幂等键；同一 telegram_id 下唯一（非空时）",
    )


class CreateTaskResponse(BaseModel):
    """创建成功后的最小响应。"""

    task_id: UUID = Field(..., description="任务 ID")
    task_code: str = Field(..., description="用户可见短任务编号")
    status: TaskStatus = Field(..., description="当前状态，创建后通常为 queued")
    queued_at: datetime = Field(..., description="入队时间")
    created: bool = Field(
        ...,
        description="是否本次新建；幂等重放时为 false，且不会再次入队",
    )


class TaskStatusResponse(BaseModel):
    """查询任务状态（轮询等）。"""

    task_id: UUID
    task_code: str = Field(..., description="用户可见短任务编号")
    status: TaskStatus
    queued_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    billable_seconds: Decimal | None = Field(
        default=None,
        description="可计费秒数；成功任务按上游时长优先、本地时长兜底",
    )
    charged_amount: Decimal | None = Field(
        default=None,
        description="实际扣费（美元）；失败/取消为 0",
    )
    pricing_version: str | None = Field(
        default=None,
        description="本次结算使用的价目版本",
    )
    result_images: list[str] = Field(
        default_factory=list,
        description="用户可见结果图片 URL；不包含上游任务 ID",
    )
    error_code: str | None = None
    error_message: str | None = None


class TaskListItem(BaseModel):
    """任务历史列表项。"""

    task_id: UUID
    task_code: str = Field(..., description="用户可见短任务编号")
    task_type: str
    status: TaskStatus
    queued_at: datetime


class TaskListResponse(BaseModel):
    """用户任务历史分页响应。"""

    tasks: list[TaskListItem]
    total: int
    returned: int
