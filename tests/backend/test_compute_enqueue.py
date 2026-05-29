"""enqueue_compute_task：broker 配置与 send_task 行为。"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.workers.compute_enqueue import (
    enqueue_compute_task,
    enqueue_compute_task_with_record,
    run_requeue_queued_compute_tasks,
)


class _FakeBegin:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def begin(self):
        return _FakeBegin()


class _FakeSessionMaker:
    def __call__(self):
        return self

    async def __aenter__(self):
        return _FakeSession()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_enqueue_without_broker_does_not_send():
    with patch("backend.workers.compute_enqueue.settings") as mock_settings:
        mock_settings.celery_broker_url = None

        assert enqueue_compute_task(uuid.uuid4()) is False


def test_enqueue_with_broker_calls_send_task():
    task_id = uuid.uuid4()
    with patch("backend.workers.compute_enqueue.settings") as mock_settings:
        mock_settings.celery_broker_url = "redis://localhost:6379/0"
        with patch("backend.workers.celery_app.celery_app.send_task") as send_task:
            assert enqueue_compute_task(task_id) is True
            send_task.assert_called_once()
            args, kwargs = send_task.call_args
            assert args[0] == "tasks.execute_compute"
            assert kwargs["args"] == [str(task_id)]
            assert kwargs["queue"] == "compute"


def test_enqueue_with_broker_returns_false_on_send_failure():
    task_id = uuid.uuid4()
    with patch("backend.workers.compute_enqueue.settings") as mock_settings:
        mock_settings.celery_broker_url = "redis://localhost:6379/0"
        with patch(
            "backend.workers.celery_app.celery_app.send_task",
            side_effect=RuntimeError("redis down"),
        ):
            assert enqueue_compute_task(task_id) is False


@pytest.mark.asyncio
async def test_requeue_skips_when_disabled():
    with patch("backend.workers.compute_enqueue.settings") as mock_settings:
        mock_settings.compute_requeue_enabled = False
        stats = await run_requeue_queued_compute_tasks()
    assert stats.scanned == 0
    assert stats.enqueued == 0


@pytest.mark.asyncio
async def test_requeue_enqueues_candidates(monkeypatch):
    task_ids = [uuid.uuid4(), uuid.uuid4()]
    rows = [
        SimpleNamespace(task_id=task_ids[0], status="queued", celery_task_id=None),
        SimpleNamespace(task_id=task_ids[1], status="queued", celery_task_id=None),
    ]

    class FakeRepo:
        async def list_requeue_candidate_tasks(
            self, *, cutoff, claim_stale_before, limit
        ):
            assert limit == 10
            return rows

    monkeypatch.setattr(
        "backend.workers.compute_enqueue.async_session_maker",
        _FakeSessionMaker(),
    )
    monkeypatch.setattr(
        "backend.workers.compute_enqueue.TaskRepository",
        lambda session: FakeRepo(),
    )
    claim = AsyncMock(side_effect=[True, True])
    enqueue = MagicMock(side_effect=[True, False])
    monkeypatch.setattr(
        "backend.workers.compute_enqueue.claim_enqueue_attempt",
        claim,
    )
    monkeypatch.setattr(
        "backend.workers.compute_enqueue.enqueue_compute_task",
        enqueue,
    )
    with patch("backend.workers.compute_enqueue.settings") as mock_settings:
        mock_settings.compute_requeue_enabled = True
        mock_settings.celery_broker_url = "redis://localhost:6379/0"
        mock_settings.compute_requeue_min_age_sec = 60
        mock_settings.compute_worker_claim_stale_sec = 300
        mock_settings.compute_requeue_batch_size = 10
        stats = await run_requeue_queued_compute_tasks()

    assert stats.scanned == 2
    assert stats.enqueued == 1
    assert stats.failed == 1
    assert stats.skipped == 0
    assert claim.await_count == 2
    assert enqueue.call_count == 2


@pytest.mark.asyncio
async def test_requeue_skips_when_enqueue_claim_is_lost(monkeypatch):
    task_id = uuid.uuid4()
    rows = [SimpleNamespace(task_id=task_id, status="queued", celery_task_id=None)]

    class FakeRepo:
        async def list_requeue_candidate_tasks(
            self, *, cutoff, claim_stale_before, limit
        ):
            return rows

    monkeypatch.setattr(
        "backend.workers.compute_enqueue.async_session_maker",
        _FakeSessionMaker(),
    )
    monkeypatch.setattr(
        "backend.workers.compute_enqueue.TaskRepository",
        lambda session: FakeRepo(),
    )
    claim = AsyncMock(return_value=False)
    enqueue = MagicMock()
    monkeypatch.setattr(
        "backend.workers.compute_enqueue.claim_enqueue_attempt",
        claim,
    )
    monkeypatch.setattr(
        "backend.workers.compute_enqueue.enqueue_compute_task",
        enqueue,
    )
    with patch("backend.workers.compute_enqueue.settings") as mock_settings:
        mock_settings.compute_requeue_enabled = True
        mock_settings.celery_broker_url = "redis://localhost:6379/0"
        mock_settings.compute_requeue_min_age_sec = 60
        mock_settings.compute_worker_claim_stale_sec = 300
        mock_settings.compute_requeue_batch_size = 10
        stats = await run_requeue_queued_compute_tasks()

    assert stats.scanned == 1
    assert stats.enqueued == 0
    assert stats.failed == 0
    assert stats.skipped == 1
    claim.assert_awaited_once()
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_requeue_clears_stale_worker_claim_before_enqueue(monkeypatch):
    task_id = uuid.uuid4()
    rows = [
        SimpleNamespace(
            task_id=task_id,
            status="queued",
            celery_task_id="dead-worker",
        )
    ]
    cleared: list[uuid.UUID] = []

    class FakeRepo:
        async def list_requeue_candidate_tasks(
            self, *, cutoff, claim_stale_before, limit
        ):
            return rows

        async def clear_stale_queued_task_claim(self, task_id, *, stale_before):
            cleared.append(task_id)
            return True

    monkeypatch.setattr(
        "backend.workers.compute_enqueue.async_session_maker",
        _FakeSessionMaker(),
    )
    monkeypatch.setattr(
        "backend.workers.compute_enqueue.TaskRepository",
        lambda session: FakeRepo(),
    )
    claim = AsyncMock(return_value=True)
    enqueue = MagicMock(return_value=True)
    monkeypatch.setattr(
        "backend.workers.compute_enqueue.claim_enqueue_attempt",
        claim,
    )
    monkeypatch.setattr(
        "backend.workers.compute_enqueue.enqueue_compute_task",
        enqueue,
    )
    with patch("backend.workers.compute_enqueue.settings") as mock_settings:
        mock_settings.compute_requeue_enabled = True
        mock_settings.celery_broker_url = "redis://localhost:6379/0"
        mock_settings.compute_requeue_min_age_sec = 60
        mock_settings.compute_worker_claim_stale_sec = 300
        mock_settings.compute_requeue_batch_size = 10
        stats = await run_requeue_queued_compute_tasks()

    assert cleared == [task_id]
    assert stats.scanned == 1
    assert stats.enqueued == 1
    assert stats.skipped == 0
    claim.assert_awaited_once()
    enqueue.assert_called_once_with(task_id)


@pytest.mark.asyncio
async def test_enqueue_with_record_claims_before_send(monkeypatch):
    task_id = uuid.uuid4()
    claim = AsyncMock(return_value=True)
    enqueue = MagicMock(return_value=True)
    monkeypatch.setattr(
        "backend.workers.compute_enqueue.claim_enqueue_attempt",
        claim,
    )
    monkeypatch.setattr(
        "backend.workers.compute_enqueue.enqueue_compute_task",
        enqueue,
    )

    ok = await enqueue_compute_task_with_record(task_id)

    assert ok is True
    claim.assert_awaited_once()
    enqueue.assert_called_once_with(task_id)
