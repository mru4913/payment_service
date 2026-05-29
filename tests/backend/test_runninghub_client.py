# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from backend.config import Settings
from backend.third_party.runninghub import (
    MISSING_API_KEY,
    CreateTaskParams,
    NodeInfo,
    RunningHubAPIError,
    RunningHubClient,
    get_runninghub_client,
    load_runninghub_priority_cost_map,
    load_runninghub_priority_instance_map,
    rh_instance_type_for_priority,
)


def _repo_root() -> Path:
    for p in Path(__file__).resolve().parents:
        if (p / "pyproject.toml").is_file():
            return p
    raise RuntimeError("repo root not found")


def _mock_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/openapi/v2/media/upload/binary"):
        if request.headers.get("Authorization") != "Bearer test-key":
            return httpx.Response(401, json={"error": "unauthorized"})
        return httpx.Response(
            200,
            json={"code": 0, "msg": "ok", "data": {"fileName": "rh/up.png"}},
        )
    if path.endswith("/task/openapi/create"):
        body = json.loads(request.content.decode("utf-8"))
        if body.get("workflowId") == "bad":
            return httpx.Response(200, json={"code": 400, "msg": "bad workflow"})
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "taskId": "tid-1",
                    "taskStatus": "QUEUED",
                    "clientId": "c1",
                },
            },
        )
    if path.endswith("/openapi/v2/query"):
        body = json.loads(request.content.decode("utf-8"))
        tid = body.get("taskId")
        if tid == "flat":
            return httpx.Response(
                200,
                json={
                    "taskId": "flat",
                    "status": "SUCCESS",
                    "results": [{"url": "https://x/a.png", "outputType": "image"}],
                },
            )
        if tid == "env":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "ok",
                    "data": {
                        "taskId": "env",
                        "status": "RUNNING",
                    },
                },
            )
        return httpx.Response(
            200,
            json={"taskId": tid, "status": "FAILED", "errorCode": "E1"},
        )
    if path.endswith("/api/openapi/getJsonApiFormat"):
        return httpx.Response(
            200,
            json={"code": 0, "data": {"prompt": '{"1": {"class_type": "LoadImage"}}'}},
        )
    if path.endswith("/task/openapi/getWebhookDetail"):
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "id": "wh-99",
                    "taskId": "tid-hook",
                    "callbackStatus": "FAILED",
                    "retryCount": 2,
                },
            },
        )
    if path.endswith("/task/openapi/retryWebhook"):
        return httpx.Response(200, json={"code": 0, "msg": "ok", "data": None})
    return httpx.Response(404, json={"error": "no route"})


@pytest.fixture
def mock_client() -> RunningHubClient:
    transport = httpx.MockTransport(_mock_handler)
    inner = httpx.AsyncClient(transport=transport)
    return RunningHubClient("test-key", client=inner, max_retries=0)


@pytest.mark.asyncio
async def test_upload_success(mock_client: RunningHubClient) -> None:
    r = await mock_client.upload_media(
        file=b"abc",
        filename="a.png",
        content_type="image/png",
    )
    assert r.file_name == "rh/up.png"
    await mock_client.aclose()


@pytest.mark.asyncio
async def test_upload_http_401() -> None:
    transport = httpx.MockTransport(_mock_handler)
    inner = httpx.AsyncClient(transport=transport)
    c = RunningHubClient("wrong", client=inner, max_retries=0)
    with pytest.raises(RunningHubAPIError) as ei:
        await c.upload_media(file=b"x", filename="f.bin", content_type=None)
    assert ei.value.http_status == 401
    await c.aclose()


@pytest.mark.asyncio
async def test_upload_rh_error_code() -> None:
    def h(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/upload/binary"):
            return httpx.Response(200, json={"code": 1, "msg": "quota"})
        return httpx.Response(404)

    inner = httpx.AsyncClient(transport=httpx.MockTransport(h))
    c = RunningHubClient("test-key", client=inner, max_retries=0)
    with pytest.raises(RunningHubAPIError) as ei:
        await c.upload_media(file=b"x", filename="f.bin", content_type=None)
    assert ei.value.rh_code == 1
    await c.aclose()
    await inner.aclose()


@pytest.mark.asyncio
async def test_create_success(mock_client: RunningHubClient) -> None:
    p = CreateTaskParams(
        workflow_id="wf-1",
        node_info_list=[NodeInfo("1", "image", "rh/up.png")],
        instance_type="plus",
    )
    r = await mock_client.create_comfy_task(p)
    assert r.task_id == "tid-1"
    assert r.task_status == "QUEUED"
    await mock_client.aclose()


@pytest.mark.asyncio
async def test_create_omits_empty_instance_type() -> None:
    captured: dict[str, Any] = {}

    def h(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/task/openapi/create"):
            captured["json"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "taskId": "t2",
                        "taskStatus": "QUEUED",
                        "clientId": "",
                    },
                },
            )
        return httpx.Response(404)

    inner = httpx.AsyncClient(transport=httpx.MockTransport(h))
    c = RunningHubClient("test-key", client=inner, max_retries=0)
    await c.create_comfy_task(
        CreateTaskParams(
            workflow_id="wf-1",
            node_info_list=[],
            instance_type="",
        )
    )
    assert "instanceType" not in captured["json"]
    await c.aclose()
    await inner.aclose()


@pytest.mark.asyncio
async def test_create_rh_business_error(mock_client: RunningHubClient) -> None:
    p = CreateTaskParams(workflow_id="bad", node_info_list=[])
    with pytest.raises(RunningHubAPIError) as ei:
        await mock_client.create_comfy_task(p)
    assert ei.value.rh_code == 400
    await mock_client.aclose()


@pytest.mark.asyncio
async def test_query_flat_and_envelope(mock_client: RunningHubClient) -> None:
    qf = await mock_client.query_task("flat")
    assert qf.status == "SUCCESS"
    assert qf.results and qf.results[0].url == "https://x/a.png"

    qe = await mock_client.query_task("env")
    assert qe.status == "RUNNING"
    assert qe.results is None

    await mock_client.aclose()


@pytest.mark.asyncio
async def test_get_workflow_json(mock_client: RunningHubClient) -> None:
    s = await mock_client.get_workflow_json("wf-doc")
    assert '"LoadImage"' in s
    await mock_client.aclose()


@pytest.mark.asyncio
async def test_get_webhook_detail(mock_client: RunningHubClient) -> None:
    d = await mock_client.get_webhook_detail("tid-hook")
    assert d.id == "wh-99"
    assert d.task_id == "tid-hook"
    assert d.callback_status == "FAILED"
    assert d.retry_count == 2
    await mock_client.aclose()


@pytest.mark.asyncio
async def test_retry_webhook(mock_client: RunningHubClient) -> None:
    await mock_client.retry_webhook("wh-99", "https://example.com/hook")
    await mock_client.aclose()


@pytest.mark.asyncio
async def test_client_requires_api_key() -> None:
    transport = httpx.MockTransport(_mock_handler)
    inner = httpx.AsyncClient(transport=transport)
    c = RunningHubClient(None, client=inner, max_retries=0)
    with pytest.raises(RunningHubAPIError) as ei:
        await c.query_task("x")
    assert ei.value.rh_code == MISSING_API_KEY
    assert not ei.value.is_retryable()
    await c.aclose()


def test_get_runninghub_client_missing_key() -> None:
    with pytest.raises(RunningHubAPIError) as ei:
        get_runninghub_client(Settings(runninghub_api_key=None))
    assert ei.value.rh_code == MISSING_API_KEY


def test_running_hub_api_error_is_retryable() -> None:
    assert RunningHubAPIError("m", rh_code=MISSING_API_KEY).is_retryable() is False
    assert RunningHubAPIError("m", rh_code=400).is_retryable() is False
    assert RunningHubAPIError("m", http_status=503).is_retryable() is True
    assert RunningHubAPIError("m", http_status=401).is_retryable() is False
    assert RunningHubAPIError("m", http_status=None).is_retryable() is True


@pytest.mark.asyncio
async def test_host_header_matches_base_url() -> None:
    seen: dict[str, str] = {}

    def h(request: httpx.Request) -> httpx.Response:
        seen["host"] = request.headers.get("Host") or ""
        return httpx.Response(200, json={"code": 0, "data": {"fileName": "x.bin"}})

    inner = httpx.AsyncClient(transport=httpx.MockTransport(h))
    c = RunningHubClient(
        "k",
        base_url="https://rh.example.com",
        client=inner,
        max_retries=0,
    )
    await c.upload_media(file=b"a", filename="f.png", content_type="image/png")
    assert seen["host"] == "rh.example.com"
    await c.aclose()
    await inner.aclose()


@pytest.mark.asyncio
async def test_create_envelope_non_object_data_errors() -> None:
    def h(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "msg": "ok", "data": "bad"})

    inner = httpx.AsyncClient(transport=httpx.MockTransport(h))
    c = RunningHubClient("k", client=inner, max_retries=0)
    with pytest.raises(RunningHubAPIError) as ei:
        await c.create_comfy_task(CreateTaskParams(workflow_id="wf", node_info_list=[]))
    assert "not a JSON object" in str(ei.value)
    await c.aclose()
    await inner.aclose()


@pytest.mark.asyncio
async def test_get_runninghub_client_ok() -> None:
    c = get_runninghub_client(
        Settings(
            runninghub_api_key="secret",
            runninghub_base_url="https://www.runninghub.cn",
        )
    )
    assert isinstance(c, RunningHubClient)
    await c.aclose()


def test_instance_type_map_from_catalog() -> None:
    catalog = _repo_root() / "backend" / "config" / "tier_platform_catalog.yaml"
    m = load_runninghub_priority_instance_map(catalog)
    costs = load_runninghub_priority_cost_map(catalog)
    assert m["lite"] == ""
    assert m["default"] == "standard"
    assert m["plus"] == "plus"
    assert costs["lite"] == Decimal("0.000016332")
    assert costs["default"] == Decimal("0.000163317")
    assert costs["plus"] == Decimal("0.000244976")
    assert rh_instance_type_for_priority("default", mapping=m) == "standard"
    assert rh_instance_type_for_priority("lite", mapping=m) == ""


@pytest.mark.asyncio
async def test_async_context_manager() -> None:
    transport = httpx.MockTransport(_mock_handler)
    inner = httpx.AsyncClient(transport=transport)
    async with RunningHubClient("test-key", client=inner) as c:
        r = await c.upload_media(file=b"x", filename="a.bin", content_type=None)
        assert r.file_name
    await inner.aclose()
