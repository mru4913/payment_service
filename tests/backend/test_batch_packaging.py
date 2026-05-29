"""Batch result packaging."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID
import zipfile

import pytest

from backend.workers import batch_results


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


@pytest.mark.asyncio
async def test_build_result_archives_preserves_directories(tmp_path, monkeypatch):
    batch_id = UUID("11111111-1111-4111-8111-111111111111")
    batch = SimpleNamespace(
        batch_id=batch_id,
        source_archive_name="photos.zip",
        archive_format="zip",
        task_type="remove_watermark",
        status="packaging",
        total_items=2,
        succeeded_items=1,
        failed_items=1,
    )
    items = [
        SimpleNamespace(
            status="succeeded",
            result_url="https://cdn.example/a.png",
            result_relative_path="girl/001.png",
            original_relative_path="girl/001.jpg",
            task_id=UUID("22222222-2222-4222-8222-222222222222"),
            error_message=None,
        ),
        SimpleNamespace(
            status="failed",
            result_url=None,
            result_relative_path=None,
            original_relative_path="girl/002.jpg",
            task_id=UUID("33333333-3333-4333-8333-333333333333"),
            error_message="bad input",
        ),
    ]
    monkeypatch.setattr(batch_results.settings, "batch_result_dir", str(tmp_path))
    monkeypatch.setattr(
        batch_results,
        "resolve_file_ref",
        AsyncMock(return_value=(b"image-bytes", "a.png", "image/png")),
    )

    paths = await batch_results._build_result_archives(batch, items)

    assert len(paths) == 1
    with zipfile.ZipFile(paths[0]) as zf:
        assert sorted(zf.namelist()) == ["girl/001.png", "manifest.json"]
        assert zf.read("girl/001.png") == b"image-bytes"
        manifest = zf.read("manifest.json").decode("utf-8")
        assert "girl/002.jpg" in manifest
        assert "bad input" in manifest


@pytest.mark.asyncio
async def test_build_result_archives_splits_when_combined_archive_is_too_large(
    tmp_path,
    monkeypatch,
):
    batch_id = UUID("11111111-1111-4111-8111-111111111111")
    batch = SimpleNamespace(
        batch_id=batch_id,
        source_archive_name="photos.zip",
        archive_format="zip",
        task_type="remove_watermark",
        status="packaging",
        total_items=2,
        succeeded_items=2,
        failed_items=0,
    )
    items = [
        SimpleNamespace(
            status="succeeded",
            result_url="ref-1",
            result_relative_path="a/001.png",
            original_relative_path="a/001.jpg",
            task_id=UUID("22222222-2222-4222-8222-222222222222"),
            error_message=None,
        ),
        SimpleNamespace(
            status="succeeded",
            result_url="ref-2",
            result_relative_path="b/002.png",
            original_relative_path="b/002.jpg",
            task_id=UUID("33333333-3333-4333-8333-333333333333"),
            error_message=None,
        ),
    ]
    monkeypatch.setattr(batch_results.settings, "batch_result_dir", str(tmp_path))
    monkeypatch.setattr(
        batch_results.settings,
        "batch_telegram_document_max_bytes",
        7000,
    )
    monkeypatch.setattr(
        batch_results,
        "resolve_file_ref",
        AsyncMock(
            side_effect=[
                (os.urandom(4096), "a.png", "image/png"),
                (os.urandom(4096), "b.png", "image/png"),
            ]
        ),
    )

    paths = await batch_results._build_result_archives(batch, items)

    assert [path.name for path in paths] == [
        "photos_result_part_001.zip",
        "photos_result_part_002.zip",
    ]
    assert all(path.stat().st_size <= 7000 for path in paths)
    for path in paths:
        with zipfile.ZipFile(path) as zf:
            assert "manifest.json" in zf.namelist()


@pytest.mark.asyncio
async def test_build_result_archives_fails_when_single_part_is_too_large(
    tmp_path,
    monkeypatch,
):
    batch_id = UUID("11111111-1111-4111-8111-111111111111")
    batch = SimpleNamespace(
        batch_id=batch_id,
        source_archive_name="photos.zip",
        archive_format="zip",
        task_type="remove_watermark",
        status="packaging",
        total_items=1,
        succeeded_items=1,
        failed_items=0,
    )
    items = [
        SimpleNamespace(
            status="succeeded",
            result_url="ref-1",
            result_relative_path="a/001.png",
            original_relative_path="a/001.jpg",
            task_id=UUID("22222222-2222-4222-8222-222222222222"),
            error_message=None,
        )
    ]
    monkeypatch.setattr(batch_results.settings, "batch_result_dir", str(tmp_path))
    monkeypatch.setattr(
        batch_results.settings,
        "batch_telegram_document_max_bytes",
        512,
    )
    monkeypatch.setattr(
        batch_results,
        "resolve_file_ref",
        AsyncMock(return_value=(os.urandom(4096), "a.png", "image/png")),
    )

    with pytest.raises(RuntimeError) as exc:
        await batch_results._build_result_archives(batch, items)

    assert "Telegram" in str(exc.value)


def test_enqueue_package_batch_result_routes_to_maintenance(monkeypatch):
    batch_id = UUID("11111111-1111-4111-8111-111111111111")
    fake_app = SimpleNamespace(send_task=MagicMock())
    monkeypatch.setattr(batch_results.settings, "celery_broker_url", "redis://x")
    monkeypatch.setattr(batch_results, "celery_app", fake_app)

    enqueued = batch_results.enqueue_package_batch_result(batch_id)

    assert enqueued is True
    fake_app.send_task.assert_called_once_with(
        "tasks.package_batch_result",
        args=[str(batch_id)],
        queue="maintenance",
    )


def test_enqueue_package_batch_result_returns_false_without_broker(monkeypatch):
    batch_id = UUID("11111111-1111-4111-8111-111111111111")
    fake_app = SimpleNamespace(send_task=MagicMock())
    monkeypatch.setattr(batch_results.settings, "celery_broker_url", "")
    monkeypatch.setattr(batch_results, "celery_app", fake_app)

    enqueued = batch_results.enqueue_package_batch_result(batch_id)

    assert enqueued is False
    fake_app.send_task.assert_not_called()


def test_enqueue_package_batch_result_returns_false_on_send_failure(monkeypatch):
    batch_id = UUID("11111111-1111-4111-8111-111111111111")
    fake_app = SimpleNamespace(send_task=MagicMock(side_effect=RuntimeError("down")))
    monkeypatch.setattr(batch_results.settings, "celery_broker_url", "redis://x")
    monkeypatch.setattr(batch_results, "celery_app", fake_app)

    enqueued = batch_results.enqueue_package_batch_result(batch_id)

    assert enqueued is False


@pytest.mark.asyncio
async def test_package_batch_result_skips_when_claim_fails(monkeypatch):
    batch_id = UUID("11111111-1111-4111-8111-111111111111")

    class FakeBatchService:
        def __init__(self, session):
            self.session = session

        async def claim_packaging_batch(self, **kwargs):
            assert kwargs["batch_id"] == batch_id
            return False

    build = AsyncMock()
    send = AsyncMock()
    monkeypatch.setattr(batch_results, "async_session_maker", _FakeSessionMaker())
    monkeypatch.setattr(batch_results, "BatchService", FakeBatchService)
    monkeypatch.setattr(batch_results, "_build_result_archives", build)
    monkeypatch.setattr(batch_results, "send_batch_result_archives_to_user", send)

    await batch_results.package_and_notify_batch(batch_id)

    build.assert_not_awaited()
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_package_batch_result_skips_send_when_claim_is_stale(monkeypatch):
    batch_id = UUID("11111111-1111-4111-8111-111111111111")
    batch = SimpleNamespace(
        batch_id=batch_id,
        telegram_id=1,
        status="packaging",
        total_items=1,
        succeeded_items=1,
        failed_items=0,
    )

    class FakeBatchService:
        def __init__(self, session):
            self.batch_repo = SimpleNamespace(
                get_by_batch_id=AsyncMock(return_value=batch)
            )

        async def claim_packaging_batch(self, **kwargs):
            return True

        async def refresh_packaging_claim(self, **kwargs):
            return kwargs

        async def list_items(self, batch_id):
            return []

    refresh = AsyncMock(side_effect=[True, False])
    build = AsyncMock(return_value=[batch_results.Path("/tmp/result.zip")])
    send = AsyncMock()
    monkeypatch.setattr(batch_results, "async_session_maker", _FakeSessionMaker())
    monkeypatch.setattr(batch_results, "BatchService", FakeBatchService)
    monkeypatch.setattr(FakeBatchService, "refresh_packaging_claim", refresh)
    monkeypatch.setattr(batch_results, "_build_result_archives", build)
    monkeypatch.setattr(batch_results, "send_batch_result_archives_to_user", send)

    await batch_results.package_and_notify_batch(batch_id)

    build.assert_awaited_once()
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_package_batch_result_does_not_notify_failure_when_fail_cas_lost(
    monkeypatch,
):
    batch_id = UUID("11111111-1111-4111-8111-111111111111")
    batch = SimpleNamespace(
        batch_id=batch_id,
        telegram_id=1,
        status="packaging",
        total_items=1,
        succeeded_items=1,
        failed_items=0,
    )

    class FakeBatchService:
        def __init__(self, session):
            self.batch_repo = SimpleNamespace(
                get_by_batch_id=AsyncMock(return_value=batch)
            )

        async def claim_packaging_batch(self, **kwargs):
            return True

        async def refresh_packaging_claim(self, **kwargs):
            return True

        async def mark_packaging_failed(self, **kwargs):
            return False

        async def list_items(self, batch_id):
            return []

    notify = AsyncMock()
    monkeypatch.setattr(batch_results, "async_session_maker", _FakeSessionMaker())
    monkeypatch.setattr(batch_results, "BatchService", FakeBatchService)
    monkeypatch.setattr(
        batch_results,
        "_build_result_archives",
        AsyncMock(side_effect=RuntimeError("stale build")),
    )
    monkeypatch.setattr(batch_results, "send_batch_failed_message_to_user", notify)

    await batch_results.package_and_notify_batch(batch_id)

    notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_package_batch_result_uses_claim_for_success_completion(monkeypatch):
    batch_id = UUID("11111111-1111-4111-8111-111111111111")
    batch = SimpleNamespace(
        batch_id=batch_id,
        telegram_id=1,
        status="packaging",
        total_items=1,
        succeeded_items=1,
        failed_items=0,
    )
    seen: dict[str, str] = {}

    class FakeBatchService:
        def __init__(self, session):
            self.batch_repo = SimpleNamespace(
                get_by_batch_id=AsyncMock(return_value=batch)
            )

        async def claim_packaging_batch(self, **kwargs):
            seen["claim_id"] = kwargs["claim_id"]
            return True

        async def refresh_packaging_claim(self, **kwargs):
            assert kwargs["claim_id"] == seen["claim_id"]
            return True

        async def begin_delivery(self, **kwargs):
            assert kwargs["claim_id"] == seen["claim_id"]
            return True

        async def complete_delivery(self, **kwargs):
            assert kwargs["claim_id"] == seen["claim_id"]
            return True

        async def list_items(self, batch_id):
            return []

    send = AsyncMock(return_value=True)
    monkeypatch.setattr(batch_results, "async_session_maker", _FakeSessionMaker())
    monkeypatch.setattr(batch_results, "BatchService", FakeBatchService)
    monkeypatch.setattr(
        batch_results,
        "_build_result_archives",
        AsyncMock(return_value=[batch_results.Path("/tmp/result.zip")]),
    )
    monkeypatch.setattr(batch_results, "send_batch_result_archives_to_user", send)

    await batch_results.package_and_notify_batch(batch_id)

    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_package_batch_result_does_not_mark_failed_after_send_success(
    monkeypatch,
):
    batch_id = UUID("11111111-1111-4111-8111-111111111111")
    batch = SimpleNamespace(
        batch_id=batch_id,
        telegram_id=1,
        status="packaging",
        total_items=1,
        succeeded_items=1,
        failed_items=0,
    )
    calls: list[str] = []

    class FakeBatchService:
        def __init__(self, session):
            self.batch_repo = SimpleNamespace(
                get_by_batch_id=AsyncMock(return_value=batch)
            )

        async def claim_packaging_batch(self, **kwargs):
            return True

        async def refresh_packaging_claim(self, **kwargs):
            return True

        async def begin_delivery(self, **kwargs):
            return True

        async def complete_delivery(self, **kwargs):
            raise RuntimeError("db down after send")

        async def mark_delivery_failed(self, **kwargs):
            calls.append("mark_delivery_failed")
            return True

        async def mark_packaging_failed(self, **kwargs):
            calls.append("mark_packaging_failed")
            return True

        async def list_items(self, batch_id):
            return []

    send = AsyncMock(return_value=True)
    notify_failed = AsyncMock()
    monkeypatch.setattr(batch_results, "async_session_maker", _FakeSessionMaker())
    monkeypatch.setattr(batch_results, "BatchService", FakeBatchService)
    monkeypatch.setattr(
        batch_results,
        "_build_result_archives",
        AsyncMock(return_value=[batch_results.Path("/tmp/result.zip")]),
    )
    monkeypatch.setattr(batch_results, "send_batch_result_archives_to_user", send)
    monkeypatch.setattr(
        batch_results,
        "send_batch_failed_message_to_user",
        notify_failed,
    )

    await batch_results.package_and_notify_batch(batch_id)

    send.assert_awaited_once()
    notify_failed.assert_not_awaited()
    assert calls == []
