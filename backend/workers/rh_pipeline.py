#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""RunningHub 任务创建管线。

职责：
1. 幂等：upstream_task_id 已有值 → 跳过
2. 查配方 → 确定 workflow_id + node 映射
3. 对 upload=true 的节点：下载文件 → upload_media → 得到 fileName
4. ``create_comfy_task`` 前申请 Redis 槽位（全局 + 每用户）；
   槽满抛 ``SlotBusyError``（Celery 重试）
5. 组 CreateTaskParams → create_comfy_task；失败则释槽
6. 写 upstream_task_id / status=running / started_at；写库失败则释槽

失败 → 写 status=failed + error_code，
再 raise ``RunningHubAPIError`` 供调用方 settle。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from ..database.repositories import TaskRepository
from ..database.session import async_session_maker
from ..domain.task_enums import TaskStatus
from ..third_party.runninghub import (
    CreateTaskParams,
    NodeInfo,
    RunningHubAPIError,
    RunningHubClient,
    get_runninghub_client,
    rh_instance_type_for_priority,
)
from ..globals import logger, settings
from ..storage.local import resolve_file_ref
from .slot_limiter import (
    SlotBusyError,
    release_slot,
    try_acquire_slot,
)
from .recipe import (
    WorkflowRecipe,
    build_node_info_list_from_recipe,
    get_recipe,
    load_recipes,
)

_recipes: dict[str, WorkflowRecipe] | None = None


def _get_recipes() -> dict[str, WorkflowRecipe]:
    global _recipes  # noqa: PLW0603
    if _recipes is None:
        _recipes = load_recipes()
    return _recipes


async def _resolve_file(ref: str) -> tuple[bytes, str, str | None]:
    """解析文件引用（本地路径或 URL），返回 (内容, 文件名, content_type)。"""
    return await resolve_file_ref(ref)


async def _mark_failed(
    task_id: uuid.UUID,
    error_code: str,
    error_message: str,
) -> None:
    """将任务标记为 failed（独立事务）。"""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with async_session_maker() as session:
        async with session.begin():
            repo = TaskRepository(session)
            task = await repo.get_by_task_id(task_id)
            if task and task.status != TaskStatus.FAILED.value:
                await repo.update(
                    task,
                    {
                        "status": TaskStatus.FAILED.value,
                        "completed_at": now,
                        "error_code": error_code[:64],
                        "error_message": error_message[:500],
                    },
                )


async def run_runninghub_pipeline(
    task_id: uuid.UUID,
    *,
    celery_task_id: str = "",
) -> None:
    """RunningHub 任务创建管线（详见模块文档）。

    成功：写 running，等 Webhook 回调推终态（Webhook 释槽）。
    失败：写 failed，raise ``RunningHubAPIError`` 供调用方 settle。
    槽位已满：raise ``SlotBusyError``（不标记 failed，由 Celery 重试）。
    """
    # ── 1. 加载任务行，幂等检查 ──
    async with async_session_maker() as session:
        async with session.begin():
            repo = TaskRepository(session)
            task = await repo.get_by_task_id(task_id)
            if not task:
                logger.warning("rh_pipeline: task not found task_id=%s", task_id)
                return
            if task.upstream_task_id:
                logger.info(
                    "rh_pipeline: skip (already submitted) task_id=%s upstream=%s",
                    task_id,
                    task.upstream_task_id,
                )
                return
            telegram_id = int(task.telegram_id)
            task_type = task.task_type
            platform = task.third_party_platform
            priority_type = task.priority_type
            input_payload: dict[str, Any] = dict(task.input_payload or {})

    # ── 2. 查配方 ──
    recipe = get_recipe(task_type, platform, recipes=_get_recipes())
    if recipe is None:
        err_msg = f"no recipe for task_type={task_type} platform={platform}"
        logger.error("rh_pipeline: %s task_id=%s", err_msg, task_id)
        await _mark_failed(task_id, "unknown_task_type", err_msg)
        raise RunningHubAPIError(err_msg)

    # ── 3. 确定 workflow_id ──
    if recipe.workflow_id is not None:
        workflow_id = recipe.workflow_id
    else:
        workflow_id = input_payload.get("workflow_id")
        if not workflow_id:
            err_msg = "input_payload missing required field 'workflow_id'"
            await _mark_failed(task_id, "missing_workflow_id", err_msg)
            raise RunningHubAPIError(err_msg)

    # ── 4. 构建 node_info_list ──
    rh_client: RunningHubClient = get_runninghub_client(settings)
    slot_acquired = False
    try:
        if recipe.nodes is not None:
            # 配方翻译模式
            uploaded: dict[str, str] = {}
            for payload_key, spec in recipe.nodes.items():
                if not spec.upload:
                    continue
                file_url = input_payload.get(payload_key)
                if not file_url:
                    err_msg = f"input_payload missing upload field '{payload_key}'"
                    await _mark_failed(task_id, "missing_upload_field", err_msg)
                    raise RunningHubAPIError(err_msg)
                content, fname, ct = await _resolve_file(str(file_url))
                upload_result = await rh_client.upload_media(
                    file=content,
                    filename=fname,
                    content_type=ct,
                )
                uploaded[payload_key] = upload_result.file_name
                logger.info(
                    "rh_pipeline: uploaded %s → %s task_id=%s",
                    payload_key,
                    upload_result.file_name,
                    task_id,
                )

            raw_nodes = build_node_info_list_from_recipe(
                recipe,
                input_payload,
                uploaded,
            )
            node_info_list = [
                NodeInfo(
                    node_id=n["node_id"],
                    field_name=n["field_name"],
                    field_value=n["field_value"],
                )
                for n in raw_nodes
            ]
        else:
            # 透传模式
            raw_list = input_payload.get("node_info_list", [])
            node_info_list = [
                NodeInfo(
                    node_id=str(n.get("node_id", "")),
                    field_name=str(n.get("field_name", "")),
                    field_value=n.get("field_value", ""),
                )
                for n in raw_list
                if isinstance(n, dict)
            ]

        # ── 5. instanceType ──
        instance_type = rh_instance_type_for_priority(priority_type)

        # ── 6. webhookUrl ──
        webhook_url: str | None = None
        if settings.runninghub_webhook_public_base_url:
            webhook_url = (
                f"{settings.runninghub_webhook_public_base_url.rstrip('/')}"
                f"/api/webhooks/runninghub/{task_id}"
            )

        # ── 7. 槽位 + create_comfy_task ──
        if not await try_acquire_slot(settings, telegram_id):
            raise SlotBusyError()
        slot_acquired = True

        params = CreateTaskParams(
            workflow_id=workflow_id,
            node_info_list=node_info_list,
            instance_type=instance_type,
            webhook_url=webhook_url,
        )
        result = await rh_client.create_comfy_task(params)

    except SlotBusyError:
        raise
    except RunningHubAPIError:
        if slot_acquired:
            await release_slot(settings, telegram_id)
            slot_acquired = False
        raise
    except httpx.HTTPError as exc:
        if slot_acquired:
            await release_slot(settings, telegram_id)
            slot_acquired = False
        err_msg = f"download/upload HTTP error: {exc}"
        await _mark_failed(task_id, "rh_network", err_msg)
        raise RunningHubAPIError(err_msg) from exc
    except Exception as exc:
        if slot_acquired:
            await release_slot(settings, telegram_id)
            slot_acquired = False
        err_msg = f"unexpected error: {exc}"
        await _mark_failed(task_id, "rh_internal", err_msg)
        raise RunningHubAPIError(err_msg) from exc
    finally:
        await rh_client.aclose()

    # ── 8. 写 running ──
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        async with async_session_maker() as session:
            async with session.begin():
                repo = TaskRepository(session)
                task = await repo.get_by_task_id(task_id)
                if not task:
                    return
                update_payload: dict[str, Any] = {
                    "upstream_task_id": result.task_id,
                    "status": TaskStatus.RUNNING.value,
                    "started_at": now,
                }
                if celery_task_id and not task.celery_task_id:
                    update_payload["celery_task_id"] = celery_task_id
                await repo.update(task, update_payload)
    except Exception:
        if slot_acquired:
            await release_slot(settings, telegram_id)
        raise

    logger.info(
        "rh_pipeline: created upstream task_id=%s upstream=%s",
        task_id,
        result.task_id,
    )
