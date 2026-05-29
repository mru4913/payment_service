"""Batch service state helpers."""

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.services.batch_service import BatchService


@pytest.mark.asyncio
async def test_mark_task_running_updates_item_and_parent_batch() -> None:
    task_id = uuid.uuid4()
    batch_id = uuid.uuid4()
    svc = BatchService.__new__(BatchService)
    svc.item_repo = SimpleNamespace(
        get_by_task_id=AsyncMock(return_value=SimpleNamespace(batch_id=batch_id)),
        mark_running_by_task_id=AsyncMock(return_value=True),
    )
    svc.batch_repo = SimpleNamespace(mark_running=AsyncMock(return_value=True))

    marked = await svc.mark_task_running(task_id)

    assert marked is True
    svc.item_repo.mark_running_by_task_id.assert_awaited_once_with(task_id)
    svc.batch_repo.mark_running.assert_awaited_once_with(batch_id)


@pytest.mark.asyncio
async def test_mark_task_running_ignores_non_batch_task() -> None:
    task_id = uuid.uuid4()
    svc = BatchService.__new__(BatchService)
    svc.item_repo = SimpleNamespace(
        get_by_task_id=AsyncMock(return_value=None),
        mark_running_by_task_id=AsyncMock(),
    )
    svc.batch_repo = SimpleNamespace(mark_running=AsyncMock())

    marked = await svc.mark_task_running(task_id)

    assert marked is False
    svc.item_repo.mark_running_by_task_id.assert_not_awaited()
    svc.batch_repo.mark_running.assert_not_awaited()


@pytest.mark.asyncio
async def test_claim_packaging_batch_delegates_to_repo() -> None:
    batch_id = uuid.uuid4()
    stale_before = datetime(2026, 1, 1, 0, 0, 0)
    svc = BatchService.__new__(BatchService)
    svc.batch_repo = SimpleNamespace(
        claim_packaging_batch=AsyncMock(return_value=True),
    )

    claimed = await svc.claim_packaging_batch(
        batch_id=batch_id,
        claim_id="claim-1",
        stale_before=stale_before,
    )

    assert claimed is True
    svc.batch_repo.claim_packaging_batch.assert_awaited_once()
    _, kwargs = svc.batch_repo.claim_packaging_batch.await_args
    assert kwargs["claim_id"] == "claim-1"
    assert kwargs["stale_before"] == stale_before


@pytest.mark.asyncio
async def test_complete_packaging_requires_claim_id() -> None:
    batch_id = uuid.uuid4()
    svc = BatchService.__new__(BatchService)
    svc.batch_repo = SimpleNamespace(
        complete_packaging_if_claimed=AsyncMock(return_value=True),
    )

    completed = await svc.complete_packaging(
        batch_id=batch_id,
        claim_id="claim-1",
        result_archive_path="/tmp/result.zip",
    )

    assert completed is True
    svc.batch_repo.complete_packaging_if_claimed.assert_awaited_once()
    _, kwargs = svc.batch_repo.complete_packaging_if_claimed.await_args
    assert kwargs["claim_id"] == "claim-1"
    assert kwargs["result_archive_path"] == "/tmp/result.zip"


@pytest.mark.asyncio
async def test_mark_packaging_failed_requires_claim_id() -> None:
    batch_id = uuid.uuid4()
    svc = BatchService.__new__(BatchService)
    svc.batch_repo = SimpleNamespace(
        mark_packaging_failed_if_claimed=AsyncMock(return_value=False),
    )

    failed = await svc.mark_packaging_failed(
        batch_id=batch_id,
        claim_id="claim-1",
        error_message="lost owner",
    )

    assert failed is False
    svc.batch_repo.mark_packaging_failed_if_claimed.assert_awaited_once()
    _, kwargs = svc.batch_repo.mark_packaging_failed_if_claimed.await_args
    assert kwargs["claim_id"] == "claim-1"
    assert kwargs["error_message"] == "lost owner"
