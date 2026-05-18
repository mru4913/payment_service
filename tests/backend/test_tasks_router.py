"""Tasks 路由：错误码映射、幂等时不重复入队。"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

from backend.api.dependencies import task_service_read, task_service_write
from backend.api.main import create_api_app
from backend.services.task_service import TaskServiceError

_MIN_CREATE_BODY = {
    "telegram_id": 1,
    "task_type": "face_swap",
    "third_party_platform": "runninghub",
    "priority_type": "lite",
    "input_payload": {"workflow_id": "wf-1"},
    "hold_amount": "1.0",
}


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


@patch("backend.api.routers.tasks.enqueue_compute_task", new_callable=AsyncMock)
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


@patch("backend.api.routers.tasks.enqueue_compute_task", new_callable=AsyncMock)
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
