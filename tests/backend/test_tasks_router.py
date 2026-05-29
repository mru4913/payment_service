"""Tasks 路由：错误码映射、幂等时不重复入队。"""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

from backend.api.dependencies import task_service_read, task_service_write
from backend.api.main import create_api_app
from backend.api.routers.tasks import REMOVE_WATERMARK_PROMPT
from backend.services.task_service import TaskServiceError

_MIN_CREATE_BODY = {
    "telegram_id": 1,
    "task_type": "face_swap",
    "third_party_platform": "runninghub",
    "priority_type": "lite",
    "input_payload": {"workflow_id": "wf-1"},
}

_REMOVE_WATERMARK_BODY = {
    "telegram_id": 1,
    "task_type": "remove_watermark",
    "third_party_platform": "runninghub",
    "priority_type": "default",
    "input_payload": {"image": " file_ref://input.png "},
}


def _task_row(tid, telegram_id: int = 1, status: str = "running"):
    ts = datetime.now(timezone.utc).replace(tzinfo=None)
    return SimpleNamespace(
        task_id=tid,
        telegram_id=telegram_id,
        status=status,
        task_type="face_swap",
        queued_at=ts,
        started_at=ts,
        completed_at=None,
        upstream_task_id="upstream-hidden",
        result_payload=None,
        billable_seconds=None,
        charged_amount=None,
        pricing_version=None,
        error_code=None,
        error_message=None,
    )


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


@pytest.mark.asyncio
async def test_post_task_insufficient_funds_returns_402(client_no_auth):
    app = client_no_auth.app

    class FakeTS:
        async def create_task_with_hold(self, **kwargs):
            raise TaskServiceError("可用余额不足", "insufficient_funds")

    async def get_ts():
        return FakeTS()

    app.dependency_overrides[task_service_write] = get_ts
    try:
        r = await client_no_auth.post("/tasks", json=_MIN_CREATE_BODY)
        assert r.status_code == 402
        body = r.json()
        assert body["detail"]["code"] == "insufficient_funds"
    finally:
        app.dependency_overrides.pop(task_service_write, None)


@patch(
    "backend.api.routers.tasks.enqueue_compute_task_with_record",
    new_callable=AsyncMock,
)
@pytest.mark.asyncio
async def test_post_task_enqueues_only_when_created(mock_enqueue, client_no_auth):
    app = client_no_auth.app
    tid = uuid4()
    ts = datetime.now(timezone.utc).replace(tzinfo=None)

    class FakeTS:
        async def create_task_with_hold(self, **kwargs):
            return (
                SimpleNamespace(task_id=tid, status="queued", queued_at=ts),
                True,
            )

    async def fake_ts():
        return FakeTS()

    app.dependency_overrides[task_service_write] = fake_ts
    try:
        r = await client_no_auth.post("/tasks", json=_MIN_CREATE_BODY)
        assert r.status_code == 200
        data = r.json()
        assert data["created"] is True
        assert data["task_id"] == str(tid)
        mock_enqueue.assert_awaited_once_with(tid)
    finally:
        app.dependency_overrides.pop(task_service_write, None)


@patch(
    "backend.api.routers.tasks.enqueue_compute_task_with_record",
    new_callable=AsyncMock,
)
@pytest.mark.asyncio
async def test_post_task_idempotent_skips_enqueue(mock_enqueue, client_no_auth):
    app = client_no_auth.app
    tid = uuid4()
    ts = datetime.now(timezone.utc).replace(tzinfo=None)

    class FakeTS:
        async def create_task_with_hold(self, **kwargs):
            return (
                SimpleNamespace(task_id=tid, status="queued", queued_at=ts),
                False,
            )

    async def fake_ts():
        return FakeTS()

    app.dependency_overrides[task_service_write] = fake_ts
    try:
        r = await client_no_auth.post("/tasks", json=_MIN_CREATE_BODY)
        assert r.status_code == 200
        assert r.json()["created"] is False
        mock_enqueue.assert_not_awaited()
    finally:
        app.dependency_overrides.pop(task_service_write, None)


@patch(
    "backend.api.routers.tasks.enqueue_compute_task_with_record",
    new_callable=AsyncMock,
)
@pytest.mark.asyncio
async def test_post_task_estimates_hold_when_missing(mock_enqueue, client_no_auth):
    app = client_no_auth.app
    tid = uuid4()
    ts = datetime.now(timezone.utc).replace(tzinfo=None)
    seen = {}

    class FakeTS:
        async def create_task_with_hold(self, **kwargs):
            seen.update(kwargs)
            return (
                SimpleNamespace(task_id=tid, status="queued", queued_at=ts),
                True,
            )

    async def fake_ts():
        return FakeTS()

    app.dependency_overrides[task_service_write] = fake_ts
    try:
        r = await client_no_auth.post("/tasks", json=_MIN_CREATE_BODY)
        assert r.status_code == 200
        assert seen["hold_amount"].as_tuple() == Decimal("0.050000").as_tuple()
        mock_enqueue.assert_awaited_once_with(tid)
    finally:
        app.dependency_overrides.pop(task_service_write, None)


@pytest.mark.asyncio
async def test_post_task_rejects_client_hold_amount(client_no_auth):
    app = client_no_auth.app

    class FakeTS:
        async def create_task_with_hold(self, **kwargs):
            raise AssertionError("invalid request should not reach service")

    async def fake_ts():
        return FakeTS()

    body = dict(_MIN_CREATE_BODY)
    body["hold_amount"] = "0.000001"
    app.dependency_overrides[task_service_write] = fake_ts
    try:
        r = await client_no_auth.post("/tasks", json=body)
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(task_service_write, None)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"prompt": "try to override"},
        {"image": "   "},
    ],
)
@pytest.mark.asyncio
async def test_post_remove_watermark_rejects_invalid_payload(
    payload,
    client_no_auth,
):
    app = client_no_auth.app

    class FakeTS:
        async def create_task_with_hold(self, **kwargs):
            raise AssertionError("invalid request should not reach service")

    async def fake_ts():
        return FakeTS()

    body = dict(_REMOVE_WATERMARK_BODY)
    body["input_payload"] = payload
    app.dependency_overrides[task_service_write] = fake_ts
    try:
        r = await client_no_auth.post("/tasks", json=body)
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "invalid_input_payload"
    finally:
        app.dependency_overrides.pop(task_service_write, None)


@patch(
    "backend.api.routers.tasks.enqueue_compute_task_with_record",
    new_callable=AsyncMock,
)
@pytest.mark.asyncio
async def test_post_remove_watermark_uses_server_hold_and_normalized_payload(
    mock_enqueue,
    client_no_auth,
):
    app = client_no_auth.app
    tid = uuid4()
    ts = datetime.now(timezone.utc).replace(tzinfo=None)
    seen = {}

    class FakeTS:
        async def create_task_with_hold(self, **kwargs):
            seen.update(kwargs)
            return (
                SimpleNamespace(task_id=tid, status="queued", queued_at=ts),
                True,
            )

    async def fake_ts():
        return FakeTS()

    app.dependency_overrides[task_service_write] = fake_ts
    try:
        r = await client_no_auth.post("/tasks", json=_REMOVE_WATERMARK_BODY)
        assert r.status_code == 200
        assert seen["hold_amount"].as_tuple() == Decimal("0.216000").as_tuple()
        assert seen["input_payload"] == {
            "image": "file_ref://input.png",
            "prompt": REMOVE_WATERMARK_PROMPT,
        }
        mock_enqueue.assert_awaited_once_with(tid)
    finally:
        app.dependency_overrides.pop(task_service_write, None)


@patch(
    "backend.api.routers.tasks.enqueue_compute_task_with_record",
    new_callable=AsyncMock,
)
@pytest.mark.asyncio
async def test_post_remove_watermark_ignores_client_prompt(
    mock_enqueue,
    client_no_auth,
):
    app = client_no_auth.app
    tid = uuid4()
    ts = datetime.now(timezone.utc).replace(tzinfo=None)
    seen = {}

    class FakeTS:
        async def create_task_with_hold(self, **kwargs):
            seen.update(kwargs)
            return (
                SimpleNamespace(task_id=tid, status="queued", queued_at=ts),
                True,
            )

    async def fake_ts():
        return FakeTS()

    body = dict(_REMOVE_WATERMARK_BODY)
    body["input_payload"] = {
        "image": "file_ref://input.png",
        "prompt": "make a totally different edit",
    }
    app.dependency_overrides[task_service_write] = fake_ts
    try:
        r = await client_no_auth.post("/tasks", json=body)
        assert r.status_code == 200
        assert seen["input_payload"]["prompt"] == REMOVE_WATERMARK_PROMPT
        assert "watermarks" in seen["input_payload"]["prompt"]
        mock_enqueue.assert_awaited_once_with(tid)
    finally:
        app.dependency_overrides.pop(task_service_write, None)


@pytest.mark.asyncio
async def test_get_task_wrong_telegram_returns_404(client_no_auth):
    app = client_no_auth.app

    class FakeTSRead:
        async def get_task_for_telegram(self, task_id, telegram_id):
            return None

    async def fake_ts_read():
        return FakeTSRead()

    app.dependency_overrides[task_service_read] = fake_ts_read
    try:
        tid = uuid4()
        r = await client_no_auth.get(f"/tasks/{tid}", params={"telegram_id": 999})
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(task_service_read, None)


@pytest.mark.asyncio
async def test_get_task_status_returns_result_images_without_upstream_id(
    client_no_auth,
):
    app = client_no_auth.app
    tid = uuid4()
    task = _task_row(tid, status="succeeded")
    task.result_payload = {
        "query": {
            "results": [
                {"url": "https://cdn.example/result.png", "output_type": "png"},
                {"url": "https://cdn.example/log.txt", "output_type": "text"},
            ]
        }
    }

    class FakeTSRead:
        async def get_task_for_telegram(self, task_id, telegram_id):
            assert task_id == tid
            assert telegram_id == 1
            return task

    async def fake_ts_read():
        return FakeTSRead()

    app.dependency_overrides[task_service_read] = fake_ts_read
    try:
        r = await client_no_auth.get(f"/tasks/{tid}", params={"telegram_id": 1})
        assert r.status_code == 200
        data = r.json()
        assert data["result_images"] == ["https://cdn.example/result.png"]
        assert "upstream_task_id" not in data
    finally:
        app.dependency_overrides.pop(task_service_read, None)


@pytest.mark.asyncio
async def test_list_tasks_returns_user_task_history(client_no_auth):
    app = client_no_auth.app
    tid = uuid4()

    class FakeTSRead:
        async def list_tasks_for_telegram(self, telegram_id, *, skip=0, limit=20):
            assert telegram_id == 1
            assert skip == 0
            assert limit == 5
            return [_task_row(tid, status="succeeded")], 1

    async def fake_ts_read():
        return FakeTSRead()

    app.dependency_overrides[task_service_read] = fake_ts_read
    try:
        r = await client_no_auth.get(
            "/tasks",
            params={"telegram_id": 1, "skip": 0, "limit": 5},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["returned"] == 1
        assert data["tasks"][0]["task_code"] == tid.hex[:8].upper()
        assert data["tasks"][0]["task_type"] == "face_swap"
        assert data["tasks"][0]["status"] == "succeeded"
        assert "upstream_task_id" not in data["tasks"][0]
    finally:
        app.dependency_overrides.pop(task_service_read, None)


@pytest.mark.asyncio
async def test_get_task_by_short_ref_returns_public_code(client_no_auth):
    app = client_no_auth.app
    tid = uuid4()

    class FakeTSRead:
        async def get_task_by_ref_for_telegram(self, task_ref, telegram_id):
            assert task_ref == str(tid).split("-", 1)[0]
            assert telegram_id == 1
            return _task_row(tid)

    async def fake_ts_read():
        return FakeTSRead()

    app.dependency_overrides[task_service_read] = fake_ts_read
    try:
        short_ref = str(tid).split("-", 1)[0]
        r = await client_no_auth.get(
            f"/tasks/ref/{short_ref}", params={"telegram_id": 1}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["task_id"] == str(tid)
        assert data["task_code"] == tid.hex[:8].upper()
        assert "upstream_task_id" not in data
    finally:
        app.dependency_overrides.pop(task_service_read, None)
