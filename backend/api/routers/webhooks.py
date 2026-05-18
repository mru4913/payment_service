#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""RunningHub Webhook 回调路由（公开，无 API Key）。

RH 在任务结束时 POST 到 ``/api/webhooks/runninghub/{task_id}``，
本路由负责：
1. 幂等校验（已终态则直接 200）
2. 解析 ``event`` / ``eventData``
3. 可选 ``query_task`` 拉齐完整 results
4. 写终态 + ``result_payload``
5. 异步结算预授权；释算力提交槽置于 ``finally``（settle 失败仍释槽，并打对账日志）
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from ...database.repositories import TaskRepository
from ...database.session import async_session_maker
from ...domain.task_enums import TaskStatus, ThirdPartyPlatform
from ...globals import logger, settings
from ...workers.query_snapshot import build_query_snapshot
from ...workers.slot_limiter import release_slot
from ...workers.task_settlement import settle_task_balance_hold_async

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

_TERMINAL_STATUSES = frozenset(
    {TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value}
)

_RH_SUCCESS_EVENTS = frozenset({"TASK_END", "SUCCESS"})
_RH_FAILURE_EVENTS = frozenset({"TASK_FAILED", "FAILED", "ERROR"})


async def _try_query_results(
    upstream_task_id: str,
) -> dict[str, Any] | None:
    """向 RH 调一次 query，拉齐 results；失败不阻塞主流程。"""
    return await build_query_snapshot(upstream_task_id, settings)


def _parse_event_data(raw: str | dict | None) -> dict[str, Any]:
    """安全解析 eventData（可能是 JSON 字符串或已解析的 dict）。"""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return {"raw": str(raw)}


@router.post("/runninghub/{task_id}")
async def runninghub_webhook(
    task_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """接收 RunningHub 任务完成回调。

    快速返回 200（RH 要求），重活异步处理。
    """
    try:
        body = await request.json()
    except Exception:
        logger.warning("webhook: invalid JSON body for task_id=%s", task_id)
        return JSONResponse({"ok": True, "msg": "invalid body"}, status_code=200)

    if not isinstance(body, dict):
        logger.warning("webhook: body is not a dict task_id=%s", task_id)
        return JSONResponse({"ok": True}, status_code=200)

    event: str = str(body.get("event", "")).upper()
    rh_task_id: str = str(body.get("taskId", ""))
    event_data_raw = body.get("eventData")

    logger.info(
        "webhook: received event=%s rh_task_id=%s task_id=%s",
        event,
        rh_task_id,
        task_id,
    )

    background_tasks.add_task(
        _process_webhook,
        task_id=task_id,
        event=event,
        rh_task_id=rh_task_id,
        event_data_raw=event_data_raw,
    )

    return JSONResponse({"ok": True}, status_code=200)


async def _process_webhook(
    *,
    task_id: uuid.UUID,
    event: str,
    rh_task_id: str,
    event_data_raw: Any,
) -> None:
    """后台处理 webhook：写终态 + 结算；释槽在 ``finally`` 保证执行。"""
    slot_telegram_id: int | None = None
    async with async_session_maker() as session:
        async with session.begin():
            repo = TaskRepository(session)
            task = await repo.get_by_task_id(task_id)

            if not task:
                logger.warning("webhook: task not found task_id=%s", task_id)
                return

            if task.status in _TERMINAL_STATUSES:
                logger.info(
                    "webhook: task already terminal task_id=%s status=%s",
                    task_id,
                    task.status,
                )
                return

            if task.third_party_platform != ThirdPartyPlatform.RUNNINGHUB:
                logger.warning(
                    "webhook: platform mismatch task_id=%s platform=%s",
                    task_id,
                    task.third_party_platform,
                )
                return

            event_data = _parse_event_data(event_data_raw)
            now = datetime.now(timezone.utc).replace(tzinfo=None)

            upstream_id = rh_task_id or task.upstream_task_id or ""
            query_results = (
                await _try_query_results(upstream_id) if upstream_id else None
            )

            result_payload: dict[str, Any] = {}
            if event_data:
                result_payload["event_data"] = event_data
            if query_results:
                result_payload["query"] = query_results

            if event in _RH_SUCCESS_EVENTS:
                slot_telegram_id = int(task.telegram_id)
                update: dict[str, Any] = {
                    "status": TaskStatus.SUCCEEDED.value,
                    "completed_at": now,
                }
                if result_payload:
                    update["result_payload"] = result_payload

                if query_results and query_results.get("results"):
                    results_list = query_results["results"]
                    if results_list:
                        update.setdefault("result_payload", {})

                await repo.update(task, update)

            elif event in _RH_FAILURE_EVENTS:
                slot_telegram_id = int(task.telegram_id)
                err_code = (
                    event_data.get("errorCode")
                    or event_data.get("error_code")
                    or (query_results or {}).get("error_code")
                    or "rh_task_failed"
                )
                err_msg = (
                    event_data.get("errorMessage")
                    or event_data.get("error_message")
                    or (query_results or {}).get("error_message")
                    or f"RunningHub event: {event}"
                )

                update = {
                    "status": TaskStatus.FAILED.value,
                    "completed_at": now,
                    "error_code": str(err_code)[:64],
                    "error_message": str(err_msg)[:500],
                }
                if result_payload:
                    update["result_payload"] = result_payload

                await repo.update(task, update)

            else:
                logger.warning(
                    "webhook: unrecognized event=%s task_id=%s, treating as info",
                    event,
                    task_id,
                )
                return

    if slot_telegram_id is not None:
        settle_failed = False
        try:
            await settle_task_balance_hold_async(task_id)
        except Exception:
            settle_failed = True
            logger.exception(
                "webhook: settle failed after terminal task_id=%s telegram_id=%s",
                task_id,
                slot_telegram_id,
            )
            logger.error(
                "webhook reconcile: task_id=%s telegram_id=%s "
                "settle_ok=0 slot_release_in_finally=1",
                task_id,
                slot_telegram_id,
            )
        finally:
            try:
                await release_slot(settings, slot_telegram_id)
            except Exception:
                logger.exception(
                    "webhook: release_slot failed task_id=%s telegram_id=%s",
                    task_id,
                    slot_telegram_id,
                )
                logger.error(
                    "webhook reconcile: task_id=%s telegram_id=%s "
                    "settle_ok=%s slot_release_ok=0",
                    task_id,
                    slot_telegram_id,
                    0 if settle_failed else 1,
                )
        if not settle_failed:
            logger.info(
                "webhook: processed event=%s task_id=%s → %s",
                event,
                task_id,
                "succeeded" if event in _RH_SUCCESS_EVENTS else "failed",
            )
