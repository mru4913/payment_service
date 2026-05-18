#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""算力任务 HTTP API — 创建任务 + 预授权、查询状态。"""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from ...domain.task_enums import TaskStatus
from ...services import TaskService, TaskServiceError
from ..dependencies import task_service_read, task_service_write
from ..schemas.tasks import CreateTaskRequest, CreateTaskResponse, TaskStatusResponse
from ...workers.compute_enqueue import enqueue_compute_task

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _task_error_to_http(exc: TaskServiceError) -> HTTPException:
    mapping: dict[str, tuple[int, str]] = {
        "user_not_found": (404, "用户不存在"),
        "user_inactive": (403, "用户未激活"),
        "insufficient_funds": (402, "可用余额不足"),
        "invalid_hold_amount": (422, "预授权金额无效"),
        "hold_not_active": (409, "冻结记录状态不允许此操作"),
        "invalid_balance_held": (409, "冻结汇总数据异常"),
        "balance_invariant": (409, "余额不变量冲突"),
        "capture_exceeds_hold": (409, "扣费超过冻结上限"),
        "invalid_capture_amount": (422, "扣费金额无效"),
    }
    status, default_detail = mapping.get(exc.code, (400, exc.message))
    return HTTPException(
        status_code=status,
        detail={"message": exc.message, "code": exc.code},
    )


@router.post("", response_model=CreateTaskResponse)
async def create_task(
    body: CreateTaskRequest,
    background_tasks: BackgroundTasks,
    task_service: TaskService = Depends(task_service_write),
):
    """创建任务并预授权冻结（`balance_held`）。"""
    try:
        task, created = await task_service.create_task_with_hold(
            telegram_id=body.telegram_id,
            task_type=body.task_type,
            third_party_platform=body.third_party_platform.value,
            priority_type=body.priority_type.value,
            input_payload=body.input_payload,
            hold_amount=body.hold_amount,
            task_description=body.task_description,
            idempotency_key=body.idempotency_key,
        )
    except TaskServiceError as e:
        raise _task_error_to_http(e) from e

    if created:
        background_tasks.add_task(enqueue_compute_task, task.task_id)

    return CreateTaskResponse(
        task_id=task.task_id,
        status=TaskStatus(task.status),
        queued_at=task.queued_at,
        created=created,
    )


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: UUID,
    telegram_id: int = Query(..., description="用于校验任务归属的 Telegram ID"),
    task_service: TaskService = Depends(task_service_read),
):
    """查询任务状态（需与创建时 `telegram_id` 一致）。"""
    task = await task_service.get_task_for_telegram(task_id, telegram_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问")

    return TaskStatusResponse(
        task_id=task.task_id,
        status=TaskStatus(task.status),
        queued_at=task.queued_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        upstream_task_id=task.upstream_task_id,
        billable_seconds=task.billable_seconds,
        charged_amount=task.charged_amount,
        pricing_version=task.pricing_version,
        error_code=task.error_code,
        error_message=task.error_message,
    )
