#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""算力任务 HTTP API — 创建任务 + 预授权、查询状态。"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from common.task_refs import public_task_code
from common.task_results import extract_result_image_urls

from ...globals import logger
from ...domain.task_enums import TaskStatus
from ...domain.task_prompts import REMOVE_WATERMARK_PROMPT
from ...services import TaskService, TaskServiceError
from ...services.task_pricing import TaskPricingError, estimate_task_hold
from ..dependencies import task_service_read, task_service_write
from ..schemas.tasks import (
    CreateTaskRequest,
    CreateTaskResponse,
    TaskListItem,
    TaskListResponse,
    TaskStatusResponse,
)
from ...workers.compute_enqueue import enqueue_compute_task_with_record

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _invalid_input_payload(message: str) -> None:
    raise HTTPException(
        status_code=422,
        detail={"message": message, "code": "invalid_input_payload"},
    )


def _validated_input_payload(
    task_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Validate task-specific user payload before any balance hold is created."""
    if task_type != "remove_watermark":
        return dict(payload or {})

    out = dict(payload or {})
    image = str(out.get("image") or "").strip()
    if not image:
        _invalid_input_payload("image is required")
    out["image"] = image
    out["prompt"] = REMOVE_WATERMARK_PROMPT
    return out


def _task_status_response(task) -> TaskStatusResponse:
    return TaskStatusResponse(
        task_id=task.task_id,
        task_code=public_task_code(task.task_id),
        status=TaskStatus(task.status),
        queued_at=task.queued_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        billable_seconds=task.billable_seconds,
        charged_amount=task.charged_amount,
        pricing_version=task.pricing_version,
        result_images=extract_result_image_urls(task.result_payload),
        error_code=task.error_code,
        error_message=task.error_message,
    )


def _task_list_item(task) -> TaskListItem:
    return TaskListItem(
        task_id=task.task_id,
        task_code=public_task_code(task.task_id),
        task_type=task.task_type,
        status=TaskStatus(task.status),
        queued_at=task.queued_at,
    )


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
    input_payload = _validated_input_payload(body.task_type, body.input_payload)
    payload_keys = sorted(input_payload.keys())
    face_count = len(input_payload.get("face_images") or [])
    try:
        hold_amount = estimate_task_hold(
            body.task_type,
            body.priority_type.value,
        )
    except TaskPricingError as e:
        logger.warning(
            "task_create_failed telegram_id=%s task_type=%s priority=%s code=%s",
            body.telegram_id,
            body.task_type,
            body.priority_type.value,
            e.code,
        )
        raise HTTPException(
            status_code=422,
            detail={"message": e.message, "code": e.code},
        ) from e
    logger.info(
        "task_create_request telegram_id=%s task_type=%s platform=%s priority=%s "
        "hold=%s idempotency=%s payload_keys=%s face_count=%s",
        body.telegram_id,
        body.task_type,
        body.third_party_platform.value,
        body.priority_type.value,
        hold_amount,
        bool(body.idempotency_key),
        ",".join(payload_keys),
        face_count,
    )
    try:
        task, created = await task_service.create_task_with_hold(
            telegram_id=body.telegram_id,
            task_type=body.task_type,
            third_party_platform=body.third_party_platform.value,
            priority_type=body.priority_type.value,
            input_payload=input_payload,
            hold_amount=hold_amount,
            task_description=body.task_description,
            idempotency_key=body.idempotency_key,
        )
    except TaskServiceError as e:
        logger.warning(
            "task_create_failed telegram_id=%s task_type=%s priority=%s code=%s",
            body.telegram_id,
            body.task_type,
            body.priority_type.value,
            e.code,
        )
        raise _task_error_to_http(e) from e

    if created:
        background_tasks.add_task(enqueue_compute_task_with_record, task.task_id)

    logger.info(
        "task_create_result task_id=%s telegram_id=%s status=%s created=%s",
        task.task_id,
        body.telegram_id,
        task.status,
        created,
    )
    return CreateTaskResponse(
        task_id=task.task_id,
        task_code=public_task_code(task.task_id),
        status=TaskStatus(task.status),
        queued_at=task.queued_at,
        created=created,
    )


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    telegram_id: int = Query(..., description="用于筛选任务归属的 Telegram ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    task_service: TaskService = Depends(task_service_read),
):
    """用户任务历史列表（按入队时间倒序）。"""
    tasks, total = await task_service.list_tasks_for_telegram(
        telegram_id,
        skip=skip,
        limit=limit,
    )
    return TaskListResponse(
        tasks=[_task_list_item(task) for task in tasks],
        total=total,
        returned=len(tasks),
    )


@router.get("/ref/{task_ref}", response_model=TaskStatusResponse)
async def get_task_status_by_ref(
    task_ref: str,
    telegram_id: int = Query(..., description="用于校验任务归属的 Telegram ID"),
    task_service: TaskService = Depends(task_service_read),
):
    """按用户可见短编号查询任务状态。"""
    task = await task_service.get_task_by_ref_for_telegram(task_ref, telegram_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问")
    return _task_status_response(task)


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

    return _task_status_response(task)
