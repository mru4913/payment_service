# -*- coding: utf-8 -*-
"""RunningHub ``query_task`` 结果摘要，供 Webhook 与轮询终态共用。"""

from __future__ import annotations

from typing import Any

from ..config import Settings
from ..globals import logger
from ..third_party.runninghub import (
    RunningHubAPIError,
    QueryTaskResult,
    RunningHubClient,
    get_runninghub_client,
)

_DURATION_KEYS = (
    "taskCostTime",
    "task_cost_time",
    "billableSeconds",
    "billable_seconds",
    "durationSeconds",
    "duration_seconds",
)


def query_task_result_to_payload(qr: QueryTaskResult) -> dict[str, Any]:
    """将 ``QueryTaskResult`` 转为与 Webhook 落库一致的 ``query`` 子结构。"""
    payload: dict[str, Any] = {"status": qr.status}
    if qr.results:
        payload["results"] = [
            {"url": r.url, "output_type": r.output_type} for r in qr.results
        ]
    if qr.error_code:
        payload["error_code"] = qr.error_code
    if qr.error_message:
        payload["error_message"] = qr.error_message
    for key in _DURATION_KEYS:
        if key in qr.raw:
            payload[key] = qr.raw[key]
            break
    return payload


async def build_query_snapshot(
    upstream_task_id: str,
    settings: Settings,
    *,
    rh_client: RunningHubClient | None = None,
) -> dict[str, Any] | None:
    """向 RH 调一次 ``query_task``，返回摘要 dict；失败返回 ``None``。

    传入 ``rh_client`` 时复用该实例且**不会**在此函数内 ``aclose``
    （由调用方管理生命周期）。
    """
    if not settings.runninghub_api_key:
        return None
    if rh_client is not None:
        try:
            qr = await rh_client.query_task(upstream_task_id)
            return query_task_result_to_payload(qr)
        except (RunningHubAPIError, Exception):
            logger.warning(
                "query_snapshot: query_task failed upstream=%s",
                upstream_task_id,
                exc_info=True,
            )
            return None

    client = get_runninghub_client(settings)
    try:
        qr = await client.query_task(upstream_task_id)
        return query_task_result_to_payload(qr)
    except (RunningHubAPIError, Exception):
        logger.warning(
            "query_snapshot: query_task failed upstream=%s",
            upstream_task_id,
            exc_info=True,
        )
        return None
    finally:
        await client.aclose()
