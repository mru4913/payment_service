"""Batch API route behavior."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

from backend.api.dependencies import batch_service_read, batch_service_write
from backend.api.main import create_api_app
from backend.services.batch_service import BatchServiceError
from backend.services.batch_archives import ExtractedBatchArchive, ExtractedBatchImage


@pytest_asyncio.fixture
async def client_no_auth():
    with patch("backend.api.auth.settings") as s:
        s.api_key = None
        app = create_api_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            client.app = app
            yield client


@patch(
    "backend.api.routers.batches.enqueue_compute_task_with_record",
    new_callable=AsyncMock,
)
@patch("backend.api.routers.batches.extract_batch_archive")
@pytest.mark.asyncio
async def test_create_batch_enqueues_child_tasks(
    mock_extract,
    mock_enqueue,
    client_no_auth,
):
    app = client_no_auth.app
    batch_id = uuid4()
    task_ids = [uuid4(), uuid4()]
    created_at = datetime.now(timezone.utc).replace(tzinfo=None)
    mock_extract.return_value = ExtractedBatchArchive(
        source_archive_name="photos.zip",
        archive_format="zip",
        images=[
            ExtractedBatchImage("a/1.png", "/tmp/1.png", 10),
            ExtractedBatchImage("a/2.png", "/tmp/2.png", 10),
        ],
    )

    class FakeBatchService:
        async def create_remove_watermark_batch(self, **kwargs):
            return SimpleNamespace(
                batch=SimpleNamespace(
                    batch_id=batch_id,
                    status="queued",
                    total_items=2,
                    estimated_hold_amount=Decimal("0.432000"),
                    created_at=created_at,
                ),
                task_ids=task_ids,
            )

    async def fake_batch_service():
        return FakeBatchService()

    app.dependency_overrides[batch_service_write] = fake_batch_service
    try:
        response = await client_no_auth.post(
            "/batches/remove-watermark",
            params={"telegram_id": 1, "priority_type": "default"},
            files={"archive": ("photos.zip", b"zip-bytes", "application/zip")},
        )
    finally:
        app.dependency_overrides.pop(batch_service_write, None)

    assert response.status_code == 200
    data = response.json()
    assert data["batch_id"] == str(batch_id)
    assert data["batch_code"] == batch_id.hex[:8].upper()
    assert data["total_items"] == 2
    assert mock_enqueue.await_count == 2


@patch("backend.api.routers.batches.cleanup_extracted_batch_archive")
@patch("backend.api.routers.batches.extract_batch_archive")
@pytest.mark.asyncio
async def test_create_batch_cleans_uploads_when_service_rejects(
    mock_extract,
    mock_cleanup,
    client_no_auth,
):
    app = client_no_auth.app
    archive = ExtractedBatchArchive(
        source_archive_name="photos.zip",
        archive_format="zip",
        images=[ExtractedBatchImage("a/1.png", "/tmp/1.png", 10)],
    )
    mock_extract.return_value = archive
    mock_cleanup.return_value = 1

    class FakeBatchService:
        async def create_remove_watermark_batch(self, **kwargs):
            raise BatchServiceError("可用余额不足", "insufficient_funds")

    async def fake_batch_service():
        return FakeBatchService()

    app.dependency_overrides[batch_service_write] = fake_batch_service
    try:
        response = await client_no_auth.post(
            "/batches/remove-watermark",
            params={"telegram_id": 1, "priority_type": "default"},
            files={"archive": ("photos.zip", b"zip-bytes", "application/zip")},
        )
    finally:
        app.dependency_overrides.pop(batch_service_write, None)

    assert response.status_code == 402
    mock_cleanup.assert_called_once_with(archive)


@pytest.mark.asyncio
async def test_list_batches_returns_public_codes(client_no_auth):
    app = client_no_auth.app
    batch_id = uuid4()
    created_at = datetime.now(timezone.utc).replace(tzinfo=None)

    class FakeBatchService:
        async def list_batches_for_telegram(self, telegram_id, *, skip=0, limit=20):
            assert telegram_id == 1
            return [
                SimpleNamespace(
                    batch_id=batch_id,
                    status="completed",
                    task_type="remove_watermark",
                    total_items=2,
                    succeeded_items=2,
                    failed_items=0,
                    created_at=created_at,
                )
            ], 1

    async def fake_batch_service():
        return FakeBatchService()

    app.dependency_overrides[batch_service_read] = fake_batch_service
    try:
        response = await client_no_auth.get(
            "/batches",
            params={"telegram_id": 1, "skip": 0, "limit": 5},
        )
    finally:
        app.dependency_overrides.pop(batch_service_read, None)

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["batches"][0]["batch_code"] == batch_id.hex[:8].upper()
