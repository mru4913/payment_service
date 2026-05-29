#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""backend/workers/rh_pipeline.py 集成测试。

用 monkeypatch 替换：
- RH client（upload_media / create_comfy_task / aclose）
- 文件解析（_resolve_file）
- DB 操作（async_session_maker + TaskRepository）
- 配方加载（_get_recipes）
- settings

不依赖真实数据库或网络。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.domain.task_enums import TaskStatus, ThirdPartyPlatform
from backend.third_party.runninghub import (
    CreateTaskResult,
    RunningHubAPIError,
    UploadResult,
)
from backend.workers.recipe import NodeSpec, WorkflowRecipe
from backend.workers.slot_limiter import SlotBusyError


def _make_task(
    task_id: uuid.UUID,
    *,
    task_type: str = "face_swap",
    platform: str = ThirdPartyPlatform.RUNNINGHUB,
    priority_type: str = "default",
    status: str = TaskStatus.QUEUED.value,
    upstream_task_id: str | None = None,
    celery_task_id: str | None = None,
    input_payload: dict[str, Any] | None = None,
) -> MagicMock:
    """创建一个类 Task 对象（MagicMock 模拟 ORM 行）。"""
    t = MagicMock()
    t.task_id = task_id
    t.task_type = task_type
    t.third_party_platform = platform
    t.priority_type = priority_type
    t.status = status
    t.upstream_task_id = upstream_task_id
    t.celery_task_id = celery_task_id
    t.input_payload = input_payload or {
        "face_images": [
            "https://example.com/face1.jpg",
            "https://example.com/face2.jpg",
        ],
        "target_image": "https://example.com/target.jpg",
        "restore": False,
    }
    t.telegram_id = 888001
    return t


_FACE_SWAP_RECIPE = WorkflowRecipe(
    task_type="face_swap",
    platform="runninghub",
    workflow_id="wf_face",
    description="AI 换脸",
    nodes={
        "face_image_1": NodeSpec("45", "image", True),
        "face_image_2": NodeSpec("46", "image", True),
        "face_image_3": NodeSpec("47", "image", True),
        "face_image_4": NodeSpec("48", "image", True),
        "target_image": NodeSpec("70", "image", True),
        "restore": NodeSpec("262", "value", False),
    },
)


@pytest.fixture()
def _patch_recipes(monkeypatch: pytest.MonkeyPatch) -> None:
    """替换 pipeline 内部的配方缓存。"""
    import backend.workers.rh_pipeline as mod  # noqa: PLC0415

    monkeypatch.setattr(mod, "_recipes", {"face_swap": _FACE_SWAP_RECIPE})


@pytest.fixture()
def mock_settings(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    import backend.workers.rh_pipeline as mod  # noqa: PLC0415

    s = MagicMock()
    s.runninghub_api_key = "test_key"
    s.runninghub_base_url = "https://rh.test"
    s.runninghub_webhook_public_base_url = "https://hook.test"
    s.slot_max_concurrent_global = 0
    s.slot_max_concurrent_per_user = 0
    monkeypatch.setattr(mod, "settings", s)
    return s


@pytest.fixture()
def mock_rh_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """替换 get_runninghub_client 返回的 client。"""
    import backend.workers.rh_pipeline as mod  # noqa: PLC0415

    client = AsyncMock()
    client.upload_media = AsyncMock(
        side_effect=[
            UploadResult(file_name="uploaded_face_1.png"),
            UploadResult(file_name="uploaded_face_2.png"),
            UploadResult(file_name="uploaded_face_3.png"),
            UploadResult(file_name="uploaded_face_4.png"),
            UploadResult(file_name="uploaded_target.png"),
        ]
    )
    client.create_comfy_task = AsyncMock(
        return_value=CreateTaskResult(task_id="rh_task_001", task_status="RUNNING")
    )
    client.aclose = AsyncMock()
    monkeypatch.setattr(mod, "get_runninghub_client", lambda _settings: client)
    return client


@pytest.fixture()
def mock_download(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    import backend.workers.rh_pipeline as mod  # noqa: PLC0415

    dl = AsyncMock(return_value=(b"fake_bytes", "img.jpg", "image/jpeg"))
    monkeypatch.setattr(mod, "_resolve_file", dl)
    return dl


class _FakeRepo:
    """模拟 TaskRepository，内存中维护一个 task dict。"""

    def __init__(self, task: MagicMock) -> None:
        self._task = task
        self.updates: list[dict[str, Any]] = []

    async def get_by_task_id(self, task_id: uuid.UUID) -> MagicMock | None:
        if self._task.task_id == task_id:
            return self._task
        return None

    async def update(self, task: Any, payload: dict[str, Any]) -> None:
        for k, v in payload.items():
            setattr(task, k, v)
        self.updates.append(payload)


@pytest.fixture()
def task_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def fake_task(task_id: uuid.UUID) -> MagicMock:
    return _make_task(task_id)


@pytest.fixture()
def fake_repo(fake_task: MagicMock) -> _FakeRepo:
    return _FakeRepo(fake_task)


@pytest.fixture()
def _patch_db(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: _FakeRepo,
) -> None:
    """替换 async_session_maker 及 TaskRepository。"""
    import backend.workers.rh_pipeline as mod  # noqa: PLC0415

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        def begin(self):
            return self

    class _FakeSessionMaker:
        def __call__(self):
            return _FakeSession()

    monkeypatch.setattr(mod, "async_session_maker", _FakeSessionMaker())
    monkeypatch.setattr(mod, "TaskRepository", lambda _session: fake_repo)
    monkeypatch.setattr(mod, "mark_batch_task_running", AsyncMock())


@pytest.mark.asyncio
@pytest.mark.usefixtures("_patch_recipes", "_patch_db", "mock_settings")
async def test_pipeline_happy_path(
    task_id: uuid.UUID,
    fake_task: MagicMock,
    fake_repo: _FakeRepo,
    mock_rh_client: MagicMock,
    mock_download: AsyncMock,
) -> None:
    from backend.workers.rh_pipeline import run_runninghub_pipeline  # noqa: PLC0415

    await run_runninghub_pipeline(task_id, celery_task_id="celery_123")

    assert mock_download.call_count == 5
    assert mock_rh_client.upload_media.call_count == 5
    assert mock_rh_client.create_comfy_task.call_count == 1

    params = mock_rh_client.create_comfy_task.call_args[0][0]
    assert params.workflow_id == "wf_face"
    assert len(params.node_info_list) == 6
    by_node = {node.node_id: node for node in params.node_info_list}
    assert by_node["45"].field_value == "uploaded_face_1.png"
    assert by_node["46"].field_value == "uploaded_face_2.png"
    assert by_node["47"].field_value == "uploaded_face_3.png"
    assert by_node["48"].field_value == "uploaded_face_4.png"
    assert by_node["70"].field_value == "uploaded_target.png"
    assert by_node["262"].field_value is False
    assert params.webhook_url is None

    assert fake_task.upstream_task_id == "rh_task_001"
    assert fake_task.status == TaskStatus.RUNNING.value
    assert fake_task.celery_task_id == "celery_123"

    mock_rh_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_patch_recipes", "_patch_db", "mock_settings")
async def test_pipeline_idempotent_skip(
    task_id: uuid.UUID,
    fake_task: MagicMock,
    mock_rh_client: MagicMock,
) -> None:
    """upstream_task_id 已有值 → 跳过。"""
    fake_task.upstream_task_id = "already_submitted"

    from backend.workers.rh_pipeline import run_runninghub_pipeline  # noqa: PLC0415

    await run_runninghub_pipeline(task_id)

    mock_rh_client.create_comfy_task.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_patch_db", "mock_settings")
async def test_pipeline_unknown_task_type(
    task_id: uuid.UUID,
    fake_task: MagicMock,
    fake_repo: _FakeRepo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无配方 → failed + raise。"""
    import backend.workers.rh_pipeline as mod  # noqa: PLC0415

    monkeypatch.setattr(mod, "_recipes", {})

    from backend.workers.rh_pipeline import run_runninghub_pipeline  # noqa: PLC0415

    with pytest.raises(RunningHubAPIError, match="no recipe"):
        await run_runninghub_pipeline(task_id)

    assert fake_task.status == TaskStatus.FAILED.value
    assert fake_task.error_code == "unknown_task_type"


@pytest.mark.asyncio
@pytest.mark.usefixtures("_patch_recipes", "_patch_db", "mock_settings")
async def test_pipeline_create_fails(
    task_id: uuid.UUID,
    fake_task: MagicMock,
    fake_repo: _FakeRepo,
    mock_download: AsyncMock,
    mock_rh_client: MagicMock,
) -> None:
    """create_comfy_task 抛异常 → failed + raise。"""
    mock_rh_client.create_comfy_task = AsyncMock(
        side_effect=RunningHubAPIError("rh error", rh_code="10001"),
    )

    from backend.workers.rh_pipeline import run_runninghub_pipeline  # noqa: PLC0415

    with pytest.raises(RunningHubAPIError):
        await run_runninghub_pipeline(task_id)

    assert fake_task.status == TaskStatus.FAILED.value
    assert fake_task.error_code == "10001"
    assert fake_task.error_message == "rh error"
    mock_rh_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_patch_recipes", "_patch_db", "mock_settings")
async def test_pipeline_no_webhook_when_base_url_empty(
    task_id: uuid.UUID,
    fake_task: MagicMock,
    mock_rh_client: MagicMock,
    mock_download: AsyncMock,
    mock_settings: MagicMock,
) -> None:
    """webhook_public_base_url 为空 → webhookUrl=None。"""
    mock_settings.runninghub_webhook_public_base_url = ""

    from backend.workers.rh_pipeline import run_runninghub_pipeline  # noqa: PLC0415

    await run_runninghub_pipeline(task_id)

    params = mock_rh_client.create_comfy_task.call_args[0][0]
    assert params.webhook_url is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("_patch_recipes", "_patch_db", "mock_settings")
async def test_pipeline_slot_busy_raises_without_create(
    task_id: uuid.UUID,
    mock_rh_client: MagicMock,
    mock_download: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.workers.rh_pipeline as mod  # noqa: PLC0415

    async def _no_slot(_settings: Any, _tid: int) -> bool:
        return False

    monkeypatch.setattr(mod, "try_acquire_slot", _no_slot)

    from backend.workers.rh_pipeline import run_runninghub_pipeline  # noqa: PLC0415

    with pytest.raises(SlotBusyError):
        await run_runninghub_pipeline(task_id)

    mock_rh_client.create_comfy_task.assert_not_awaited()
    mock_rh_client.aclose.assert_awaited_once()
