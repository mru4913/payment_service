# -*- coding: utf-8 -*-
"""``poll_tasks`` / ``tasks.poll_terminal`` 单元测试（Mock，无真实 DB/RH）。"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.config import Settings
from backend.domain.task_enums import TaskStatus
from backend.third_party.runninghub import QueryTaskResult
from backend.workers import celery_tasks, poll_tasks
from backend.workers.query_snapshot import (
    build_query_snapshot,
    query_task_result_to_payload,
)


@pytest.fixture(autouse=True)
def _skip_batch_terminal_side_effects(monkeypatch):
    """Poll unit tests are DB-free unless a case explicitly opts into batch behavior."""
    monkeypatch.setattr(
        poll_tasks,
        "handle_batch_task_terminal",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        poll_tasks,
        "batch_success_missing_result",
        AsyncMock(return_value=False),
    )


def test_anchor_time_prefers_started_at():
    t = MagicMock()
    t.started_at = datetime(2024, 1, 2)
    t.queued_at = datetime(2024, 1, 1)
    assert poll_tasks._anchor_time(t) == t.started_at


def test_anchor_time_falls_back_to_queued_at():
    t = MagicMock()
    t.started_at = None
    t.queued_at = datetime(2024, 1, 1)
    assert poll_tasks._anchor_time(t) == t.queued_at


@pytest.mark.asyncio
async def test_run_poll_terminal_batch_skips_when_disabled(monkeypatch):
    monkeypatch.setattr(poll_tasks.settings, "poll_enabled", False)
    spy = AsyncMock()
    monkeypatch.setattr(poll_tasks.TaskRepository, "list_pollable_running_tasks", spy)
    await poll_tasks.run_poll_terminal_batch()
    spy.assert_not_called()


@pytest.mark.asyncio
async def test_run_poll_terminal_batch_skips_without_api_key(monkeypatch):
    monkeypatch.setattr(poll_tasks.settings, "poll_enabled", True)
    monkeypatch.setattr(poll_tasks.settings, "runninghub_api_key", None)
    spy = AsyncMock()
    monkeypatch.setattr(poll_tasks.TaskRepository, "list_pollable_running_tasks", spy)
    await poll_tasks.run_poll_terminal_batch()
    spy.assert_not_called()


class _FakeRhClient:
    """最小 async 上下文，供轮询 tick 单测复用。"""

    def __init__(self) -> None:
        self.aclose = AsyncMock()

    async def __aenter__(self) -> _FakeRhClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()


@pytest.mark.asyncio
async def test_run_poll_terminal_batch_warns_when_broker_unset(
    monkeypatch, caplog
):
    monkeypatch.setattr(poll_tasks.settings, "poll_enabled", True)
    monkeypatch.setattr(poll_tasks.settings, "runninghub_api_key", "k")
    monkeypatch.setattr(poll_tasks.settings, "celery_broker_url", None)
    monkeypatch.setattr(
        poll_tasks.TaskRepository,
        "list_pollable_running_tasks",
        AsyncMock(return_value=[]),
    )
    fake = _FakeRhClient()
    monkeypatch.setattr(poll_tasks, "get_runninghub_client", lambda _s: fake)

    with caplog.at_level(logging.WARNING):
        await poll_tasks.run_poll_terminal_batch()

    assert any("CELERY_BROKER_URL" in r.message for r in caplog.records)
    fake.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_query_snapshot_uses_injected_client(monkeypatch):
    s = Settings()
    monkeypatch.setattr(s, "runninghub_api_key", "x")

    qr = QueryTaskResult(
        task_id="t1",
        status="RUNNING",
        error_code="",
        error_message="",
        results=None,
        client_id="",
        prompt_tips="",
        raw={},
    )
    inj = MagicMock()
    inj.query_task = AsyncMock(return_value=qr)

    out = await build_query_snapshot("up-1", s, rh_client=inj)
    assert out == {"status": "RUNNING"}
    inj.query_task.assert_awaited_once_with("up-1")
    inj.aclose.assert_not_called()


def test_query_task_result_to_payload_minimal():
    qr = QueryTaskResult(
        task_id="t1",
        status="SUCCESS",
        error_code="",
        error_message="",
        results=None,
        client_id="",
        prompt_tips="",
        raw={},
    )
    assert query_task_result_to_payload(qr) == {"status": "SUCCESS"}


def test_query_task_result_to_payload_keeps_duration():
    qr = QueryTaskResult(
        task_id="t1",
        status="SUCCESS",
        error_code="",
        error_message="",
        results=None,
        client_id="",
        prompt_tips="",
        raw={"taskCostTime": "12.3"},
    )
    assert query_task_result_to_payload(qr) == {
        "status": "SUCCESS",
        "taskCostTime": "12.3",
    }


def test_poll_terminal_status_aliases_are_terminal():
    assert "COMPLETED" in poll_tasks._SUCCESS_STATUSES
    assert "ERROR" in poll_tasks._FAILED_STATUSES


@pytest.mark.asyncio
async def test_handle_query_success_notifies_user(monkeypatch):
    tid = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    qr = QueryTaskResult(
        task_id="up-1",
        status="SUCCESS",
        results=[
            MagicMock(url="https://cdn.example/result.png", output_type="png"),
        ],
        raw={},
    )
    rh = MagicMock()
    rh.query_task = AsyncMock(return_value=qr)

    async def fake_cas(self, task_id, **kwargs):
        assert task_id == tid
        assert kwargs["terminal_status"] == TaskStatus.SUCCEEDED.value
        assert kwargs["result_payload"]["query"]["results"][0]["url"].endswith(
            "result.png"
        )
        return True

    monkeypatch.setattr(
        poll_tasks.TaskRepository,
        "cas_transition_running_to_terminal",
        fake_cas,
    )
    monkeypatch.setattr(
        poll_tasks,
        "settle_task_balance_hold_async",
        AsyncMock(),
    )
    monkeypatch.setattr(poll_tasks, "release_slot", AsyncMock())
    notify = AsyncMock()
    monkeypatch.setattr(poll_tasks, "send_task_success_images_to_user", notify)

    outer = MagicMock()

    class _Begin:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *a):
            return None

    outer.begin = lambda: _Begin()

    class _Sess:
        async def __aenter__(self):
            return outer

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(
        poll_tasks.async_session_maker,
        "__call__",
        lambda: _Sess(),
    )

    stats = poll_tasks._PollBatchCounters()

    await poll_tasks._handle_query_outcome(
        task_id=tid,
        telegram_id=7,
        upstream_task_id="up-1",
        now=now,
        rh_client=rh,
        stats=stats,
    )

    notify.assert_awaited_once()
    kwargs = notify.await_args.kwargs
    assert kwargs["telegram_id"] == 7
    assert kwargs["task_id"] == tid
    assert kwargs["result_payload"]["query"]["results"][0]["output_type"] == "png"


@pytest.mark.asyncio
async def test_handle_query_success_skips_single_notify_for_batch(monkeypatch):
    tid = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    qr = QueryTaskResult(
        task_id="up-1",
        status="SUCCESS",
        results=[
            MagicMock(url="https://cdn.example/result.png", output_type="png"),
        ],
        raw={},
    )
    rh = MagicMock()
    rh.query_task = AsyncMock(return_value=qr)
    monkeypatch.setattr(
        poll_tasks.TaskRepository,
        "cas_transition_running_to_terminal",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(poll_tasks, "settle_task_balance_hold_async", AsyncMock())
    monkeypatch.setattr(poll_tasks, "release_slot", AsyncMock())
    monkeypatch.setattr(
        poll_tasks,
        "handle_batch_task_terminal",
        AsyncMock(return_value=True),
    )
    notify = AsyncMock()
    monkeypatch.setattr(poll_tasks, "send_task_success_images_to_user", notify)

    outer = MagicMock()

    class _Begin:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *a):
            return None

    outer.begin = lambda: _Begin()

    class _Sess:
        async def __aenter__(self):
            return outer

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(
        poll_tasks.async_session_maker,
        "__call__",
        lambda: _Sess(),
    )

    await poll_tasks._handle_query_outcome(
        task_id=tid,
        telegram_id=7,
        upstream_task_id="up-1",
        now=now,
        rh_client=rh,
        stats=poll_tasks._PollBatchCounters(),
    )

    notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_query_success_without_image_fails_batch_task(monkeypatch):
    tid = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    qr = QueryTaskResult(
        task_id="up-1",
        status="SUCCESS",
        results=[],
        raw={},
    )
    rh = MagicMock()
    rh.query_task = AsyncMock(return_value=qr)

    async def fake_cas(self, task_id, **kwargs):
        assert task_id == tid
        assert kwargs["terminal_status"] == TaskStatus.FAILED.value
        assert kwargs["error_code"] == "batch_no_result_image"
        assert kwargs["error_message"] == "任务成功但未返回结果图片"
        return True

    monkeypatch.setattr(
        poll_tasks,
        "batch_success_missing_result",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        poll_tasks.TaskRepository,
        "cas_transition_running_to_terminal",
        fake_cas,
    )
    monkeypatch.setattr(poll_tasks, "settle_task_balance_hold_async", AsyncMock())
    monkeypatch.setattr(poll_tasks, "release_slot", AsyncMock())
    handle_batch = AsyncMock(return_value=True)
    monkeypatch.setattr(poll_tasks, "handle_batch_task_terminal", handle_batch)
    success_notify = AsyncMock()
    failed_notify = AsyncMock()
    monkeypatch.setattr(
        poll_tasks,
        "send_task_success_images_to_user",
        success_notify,
    )
    monkeypatch.setattr(
        poll_tasks,
        "send_task_failed_message_to_user",
        failed_notify,
    )

    outer = MagicMock()

    class _Begin:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *a):
            return None

    outer.begin = lambda: _Begin()

    class _Sess:
        async def __aenter__(self):
            return outer

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(
        poll_tasks.async_session_maker,
        "__call__",
        lambda: _Sess(),
    )

    await poll_tasks._handle_query_outcome(
        task_id=tid,
        telegram_id=7,
        upstream_task_id="up-1",
        now=now,
        rh_client=rh,
        stats=poll_tasks._PollBatchCounters(),
    )

    handle_batch.assert_awaited_once()
    assert handle_batch.await_args.kwargs["terminal_status"] == TaskStatus.FAILED.value
    success_notify.assert_not_awaited()
    failed_notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_query_failure_notifies_user(monkeypatch):
    tid = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    qr = QueryTaskResult(
        task_id="up-1",
        status="FAILED",
        error_code="bad_prompt",
        error_message="upstream rejected",
        results=None,
        raw={},
    )
    rh = MagicMock()
    rh.query_task = AsyncMock(return_value=qr)

    async def fake_cas(self, task_id, **kwargs):
        assert task_id == tid
        assert kwargs["terminal_status"] == TaskStatus.FAILED.value
        assert kwargs["error_code"] == "bad_prompt"
        assert kwargs["error_message"] == "upstream rejected"
        return True

    monkeypatch.setattr(
        poll_tasks.TaskRepository,
        "cas_transition_running_to_terminal",
        fake_cas,
    )
    monkeypatch.setattr(
        poll_tasks,
        "settle_task_balance_hold_async",
        AsyncMock(),
    )
    monkeypatch.setattr(poll_tasks, "release_slot", AsyncMock())
    notify = AsyncMock()
    monkeypatch.setattr(poll_tasks, "send_task_failed_message_to_user", notify)

    outer = MagicMock()

    class _Begin:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *a):
            return None

    outer.begin = lambda: _Begin()

    class _Sess:
        async def __aenter__(self):
            return outer

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(
        poll_tasks.async_session_maker,
        "__call__",
        lambda: _Sess(),
    )

    stats = poll_tasks._PollBatchCounters()

    await poll_tasks._handle_query_outcome(
        task_id=tid,
        telegram_id=7,
        upstream_task_id="up-1",
        now=now,
        rh_client=rh,
        stats=stats,
    )

    notify.assert_awaited_once()
    kwargs = notify.await_args.kwargs
    assert kwargs["telegram_id"] == 7
    assert kwargs["task_id"] == tid
    assert kwargs["error_message"] == "upstream rejected"


@pytest.mark.asyncio
async def test_handle_timeout_discard_settles_on_cas_true(monkeypatch):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    tid = uuid.uuid4()
    anchor = now - timedelta(hours=3)

    monkeypatch.setattr(poll_tasks.settings, "poll_max_running_sec", 7200)

    settle_calls: list[uuid.UUID] = []
    release_calls: list[int] = []

    monkeypatch.setattr(
        poll_tasks,
        "build_query_snapshot",
        AsyncMock(return_value={"status": "RUNNING"}),
    )

    async def fake_cas(self, task_id, **kwargs):
        assert task_id == tid
        assert kwargs["terminal_status"] == TaskStatus.FAILED.value
        assert kwargs["error_code"] == poll_tasks.POLL_TIMEOUT_ERROR_CODE
        return True

    monkeypatch.setattr(
        poll_tasks.TaskRepository,
        "cas_transition_running_to_terminal",
        fake_cas,
    )

    async def fake_settle(task_id: uuid.UUID) -> None:
        settle_calls.append(task_id)

    async def fake_release(_settings, tg: int) -> None:
        release_calls.append(tg)

    monkeypatch.setattr(poll_tasks, "settle_task_balance_hold_async", fake_settle)
    monkeypatch.setattr(poll_tasks, "release_slot", fake_release)
    notify = AsyncMock()
    monkeypatch.setattr(poll_tasks, "send_task_failed_message_to_user", notify)

    outer = MagicMock()

    class _Begin:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *a):
            return None

    outer.begin = lambda: _Begin()

    class _Sess:
        async def __aenter__(self):
            return outer

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(
        poll_tasks.async_session_maker,
        "__call__",
        lambda: _Sess(),
    )

    rh = MagicMock()
    stats = poll_tasks._PollBatchCounters()

    await poll_tasks._handle_timeout_discard(
        task_id=tid,
        telegram_id=7,
        upstream_task_id="up-1",
        anchor=anchor,
        now=now,
        rh_client=rh,
        stats=stats,
    )
    assert settle_calls == [tid]
    assert release_calls == [7]
    notify.assert_awaited_once()
    assert notify.await_args.kwargs["telegram_id"] == 7
    assert notify.await_args.kwargs["task_id"] == tid
    assert "running exceeded" in notify.await_args.kwargs["error_message"]


@pytest.mark.asyncio
async def test_handle_query_failure_does_not_notify_on_cas_miss(monkeypatch):
    tid = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    qr = QueryTaskResult(
        task_id="up-1",
        status="FAILED",
        error_code="bad_prompt",
        error_message="upstream rejected",
        results=None,
        raw={},
    )
    rh = MagicMock()
    rh.query_task = AsyncMock(return_value=qr)

    monkeypatch.setattr(
        poll_tasks.TaskRepository,
        "cas_transition_running_to_terminal",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(poll_tasks, "settle_task_balance_hold_async", AsyncMock())
    monkeypatch.setattr(poll_tasks, "release_slot", AsyncMock())
    notify = AsyncMock()
    monkeypatch.setattr(poll_tasks, "send_task_failed_message_to_user", notify)

    outer = MagicMock()

    class _Begin:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *a):
            return None

    outer.begin = lambda: _Begin()

    class _Sess:
        async def __aenter__(self):
            return outer

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(
        poll_tasks.async_session_maker,
        "__call__",
        lambda: _Sess(),
    )

    stats = poll_tasks._PollBatchCounters()

    await poll_tasks._handle_query_outcome(
        task_id=tid,
        telegram_id=7,
        upstream_task_id="up-1",
        now=now,
        rh_client=rh,
        stats=stats,
    )

    notify.assert_not_awaited()


def test_poll_terminal_celery_task_invokes_asyncio_run():
    _real = asyncio.run

    def _run_sync(coro):
        _real(coro)

    with patch.object(celery_tasks.asyncio, "run", side_effect=_run_sync):
        with patch.object(
            celery_tasks,
            "run_poll_terminal_batch",
            new_callable=AsyncMock,
        ) as batch:
            celery_tasks.poll_terminal_task()
    batch.assert_awaited_once()
