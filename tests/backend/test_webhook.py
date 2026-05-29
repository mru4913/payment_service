#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""backend/api/routers/webhooks.py 单元测试。

用 monkeypatch 替换 DB 操作、RH client query、settle 结算。
不依赖真实数据库或网络。
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from backend.api.main import create_api_app
from backend.api.routers.webhooks import _parse_event_data, _process_webhook
from backend.domain.task_enums import TaskStatus, ThirdPartyPlatform


def _make_task(
    task_id: uuid.UUID,
    *,
    status: str = TaskStatus.RUNNING.value,
    platform: str = ThirdPartyPlatform.RUNNINGHUB,
    upstream_task_id: str | None = "rh-123",
    telegram_id: int = 999001,
) -> MagicMock:
    t = MagicMock()
    t.task_id = task_id
    t.status = status
    t.third_party_platform = platform
    t.upstream_task_id = upstream_task_id
    t.telegram_id = telegram_id
    return t


# ── _parse_event_data ──


class TestParseEventData:
    def test_none(self):
        assert _parse_event_data(None) == {}

    def test_dict(self):
        d = {"foo": "bar"}
        assert _parse_event_data(d) == d

    def test_json_string(self):
        s = json.dumps({"taskCostTime": 42})
        result = _parse_event_data(s)
        assert result == {"taskCostTime": 42}

    def test_invalid_json_string(self):
        assert _parse_event_data("not-json") == {"raw": "not-json"}

    def test_non_dict_json(self):
        assert _parse_event_data("[1,2,3]") == {"raw": "[1,2,3]"}


# ── _process_webhook ──


@pytest.mark.asyncio
async def test_runninghub_webhook_route_not_mounted_for_mvp():
    app = create_api_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/webhooks/runninghub/{uuid.uuid4()}",
            json={"event": "TASK_END"},
        )

    assert response.status_code == 404


@pytest.fixture()
def _patch_db_and_settle(monkeypatch):
    """统一 patch DB session 和 settle 函数；fixture 返回控制对象。"""

    task_store: dict[uuid.UUID, MagicMock] = {}
    updates: list[tuple[uuid.UUID, dict]] = []
    settle_calls: list[uuid.UUID] = []
    release_calls: list[int] = []

    mock_repo = MagicMock()

    async def mock_get_by_task_id(tid):
        return task_store.get(tid)

    async def mock_update(task_obj, payload):
        updates.append((task_obj.task_id, payload))
        for k, v in payload.items():
            setattr(task_obj, k, v)

    mock_repo.get_by_task_id = AsyncMock(side_effect=mock_get_by_task_id)
    mock_repo.update = AsyncMock(side_effect=mock_update)

    mock_session = AsyncMock()
    mock_begin = AsyncMock()

    async def begin_ctx(*a, **kw):
        return mock_begin

    mock_begin.__aenter__ = AsyncMock(return_value=None)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin)

    monkeypatch.setattr(
        "backend.api.routers.webhooks.async_session_maker",
        MagicMock(return_value=mock_session),
    )
    monkeypatch.setattr(
        "backend.api.routers.webhooks.TaskRepository",
        MagicMock(return_value=mock_repo),
    )

    async def fake_settle(tid):
        settle_calls.append(tid)

    monkeypatch.setattr(
        "backend.api.routers.webhooks.settle_task_balance_hold_async",
        fake_settle,
    )

    async def fake_release(_settings, telegram_id: int) -> None:
        release_calls.append(telegram_id)

    monkeypatch.setattr(
        "backend.api.routers.webhooks.release_slot",
        fake_release,
    )

    monkeypatch.setattr(
        "backend.api.routers.webhooks._try_query_results",
        AsyncMock(return_value=None),
    )

    return task_store, updates, settle_calls, release_calls


@pytest.mark.asyncio
async def test_success_event_writes_succeeded(_patch_db_and_settle):
    task_store, updates, settle_calls, release_calls = _patch_db_and_settle
    tid = uuid.uuid4()
    task_store[tid] = _make_task(tid)

    await _process_webhook(
        task_id=tid,
        event="TASK_END",
        rh_task_id="rh-123",
        event_data_raw=json.dumps({"taskCostTime": 10}),
    )

    assert len(updates) == 1
    _, payload = updates[0]
    assert payload["status"] == TaskStatus.SUCCEEDED.value
    assert payload["completed_at"] is not None
    assert "event_data" in payload.get("result_payload", {})
    assert settle_calls == [tid]
    assert release_calls == [999001]


@pytest.mark.asyncio
async def test_failure_event_writes_failed(_patch_db_and_settle):
    task_store, updates, settle_calls, release_calls = _patch_db_and_settle
    tid = uuid.uuid4()
    task_store[tid] = _make_task(tid)

    await _process_webhook(
        task_id=tid,
        event="TASK_FAILED",
        rh_task_id="rh-123",
        event_data_raw=json.dumps(
            {"errorCode": "1501", "errorMessage": "content unsafe"}
        ),
    )

    assert len(updates) == 1
    _, payload = updates[0]
    assert payload["status"] == TaskStatus.FAILED.value
    assert payload["error_code"] == "1501"
    assert "content unsafe" in payload["error_message"]
    assert settle_calls == [tid]
    assert release_calls == [999001]


@pytest.mark.asyncio
async def test_idempotent_terminal_skips(_patch_db_and_settle):
    task_store, updates, settle_calls, release_calls = _patch_db_and_settle
    tid = uuid.uuid4()
    task_store[tid] = _make_task(tid, status=TaskStatus.SUCCEEDED.value)

    await _process_webhook(
        task_id=tid,
        event="TASK_END",
        rh_task_id="rh-123",
        event_data_raw=None,
    )

    assert len(updates) == 0
    assert len(settle_calls) == 0
    assert release_calls == []


@pytest.mark.asyncio
async def test_task_not_found_does_nothing(_patch_db_and_settle):
    task_store, updates, settle_calls, release_calls = _patch_db_and_settle

    await _process_webhook(
        task_id=uuid.uuid4(),
        event="TASK_END",
        rh_task_id="rh-123",
        event_data_raw=None,
    )

    assert len(updates) == 0
    assert len(settle_calls) == 0
    assert release_calls == []


@pytest.mark.asyncio
async def test_platform_mismatch_skips(_patch_db_and_settle):
    task_store, updates, settle_calls, release_calls = _patch_db_and_settle
    tid = uuid.uuid4()
    task_store[tid] = _make_task(tid, platform="other_platform")

    await _process_webhook(
        task_id=tid,
        event="TASK_END",
        rh_task_id="rh-123",
        event_data_raw=None,
    )

    assert len(updates) == 0
    assert len(settle_calls) == 0
    assert release_calls == []


@pytest.mark.asyncio
async def test_unrecognized_event_skips(_patch_db_and_settle):
    task_store, updates, settle_calls, release_calls = _patch_db_and_settle
    tid = uuid.uuid4()
    task_store[tid] = _make_task(tid)

    await _process_webhook(
        task_id=tid,
        event="UNKNOWN_EVENT",
        rh_task_id="rh-123",
        event_data_raw=None,
    )

    assert len(updates) == 0
    assert len(settle_calls) == 0
    assert release_calls == []


@pytest.mark.asyncio
async def test_query_results_merged_into_result_payload(
    _patch_db_and_settle, monkeypatch
):
    task_store, updates, settle_calls, release_calls = _patch_db_and_settle
    tid = uuid.uuid4()
    task_store[tid] = _make_task(tid)

    query_result = {
        "status": "SUCCESS",
        "results": [{"url": "https://cdn.rh.cn/out.png", "output_type": "image"}],
    }
    monkeypatch.setattr(
        "backend.api.routers.webhooks._try_query_results",
        AsyncMock(return_value=query_result),
    )

    await _process_webhook(
        task_id=tid,
        event="TASK_END",
        rh_task_id="rh-123",
        event_data_raw=None,
    )

    assert len(updates) == 1
    _, payload = updates[0]
    rp = payload["result_payload"]
    assert rp["query"]["results"][0]["url"] == "https://cdn.rh.cn/out.png"
    assert settle_calls == [tid]
    assert release_calls == [999001]


@pytest.mark.asyncio
async def test_failure_with_query_fallback_error_fields(
    _patch_db_and_settle, monkeypatch
):
    """eventData 无 errorCode 时，从 query 结果中回退取值。"""
    task_store, updates, settle_calls, release_calls = _patch_db_and_settle
    tid = uuid.uuid4()
    task_store[tid] = _make_task(tid)

    query_result = {
        "status": "FAILED",
        "error_code": "1003",
        "error_message": "rate limited",
    }
    monkeypatch.setattr(
        "backend.api.routers.webhooks._try_query_results",
        AsyncMock(return_value=query_result),
    )

    await _process_webhook(
        task_id=tid,
        event="TASK_FAILED",
        rh_task_id="rh-123",
        event_data_raw="{}",
    )

    _, payload = updates[0]
    assert payload["error_code"] == "1003"
    assert "rate limited" in payload["error_message"]
    assert settle_calls == [tid]
    assert release_calls == [999001]


@pytest.mark.asyncio
async def test_settle_failure_still_releases_slot(_patch_db_and_settle, monkeypatch):
    """终态已写库后 settle 抛错，仍须在 finally 释槽（避免计数泄漏）。"""
    task_store, updates, settle_calls, release_calls = _patch_db_and_settle
    tid = uuid.uuid4()
    task_store[tid] = _make_task(tid)

    async def failing_settle(_task_uuid: uuid.UUID) -> None:
        raise RuntimeError("settle failed for test")

    monkeypatch.setattr(
        "backend.api.routers.webhooks.settle_task_balance_hold_async",
        failing_settle,
    )

    await _process_webhook(
        task_id=tid,
        event="TASK_FAILED",
        rh_task_id="rh-123",
        event_data_raw="{}",
    )

    assert len(updates) == 1
    assert release_calls == [999001]
