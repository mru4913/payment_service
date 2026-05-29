# -*- coding: utf-8 -*-
"""frontend.integrations.BackendClient 单元测试（MockTransport）。"""

import json
from decimal import Decimal
from uuid import UUID

import httpx
import pytest

from frontend.integrations.backend_client import BackendClient, task_body_for_create
from frontend.integrations.backend_errors import BackendAPIError, parse_error_detail
from frontend.integrations.settings import BotBackendSettings


@pytest.fixture
def settings() -> BotBackendSettings:
    return BotBackendSettings(
        base_url="http://test",
        api_key="secret",
        connect_timeout=1.0,
        read_timeout=5.0,
    )


async def _swap_client(client: BackendClient, transport: httpx.MockTransport) -> None:
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        transport=transport,
        base_url=client._settings.base_url,
        headers={"X-API-Key": "secret"} if client._settings.api_key else {},
        timeout=httpx.Timeout(5.0),
    )


@pytest.mark.asyncio
async def test_get_user_success(settings: BotBackendSettings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-API-Key") == "secret"
        assert request.url.path == "/users/42"
        return httpx.Response(
            200,
            json={
                "telegram_id": 42,
                "balance": "1.5",
                "balance_held": "0.5",
                "balance_available": "1",
                "total_deposits": "10",
                "total_withdrawals": "0",
            },
        )

    client = BackendClient(settings)
    await _swap_client(client, httpx.MockTransport(handler))
    try:
        data = await client.get_user(42)
        assert data["telegram_id"] == 42
        assert Decimal(str(data["balance"])) == Decimal("1.5")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_create_task_insufficient_funds(settings: BotBackendSettings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/tasks"
        json.loads(request.content.decode())
        return httpx.Response(
            402,
            json={"detail": {"message": "可用余额不足", "code": "insufficient_funds"}},
        )

    client = BackendClient(settings)
    await _swap_client(client, httpx.MockTransport(handler))
    try:
        body = task_body_for_create(
            telegram_id=1,
            task_type="face_swap",
            third_party_platform="runninghub",
            priority_type="default",
            input_payload={
                "source_image": "https://a/x.jpg",
                "target_image": "https://b/y.jpg",
            },
        )
        with pytest.raises(BackendAPIError) as ei:
            await client.create_task(body)
        assert ei.value.http_status == 402
        assert ei.value.code == "insufficient_funds"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_list_user_tasks_endpoint(settings: BotBackendSettings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/tasks"
        assert request.url.params["telegram_id"] == "42"
        assert request.url.params["skip"] == "5"
        assert request.url.params["limit"] == "5"
        return httpx.Response(
            200,
            json={
                "tasks": [
                    {
                        "task_id": "00000000-0000-4000-8000-000000000001",
                        "task_code": "00000000",
                        "task_type": "face_swap",
                        "status": "succeeded",
                        "queued_at": "2026-05-18T10:00:00",
                    }
                ],
                "total": 6,
                "returned": 1,
            },
        )

    client = BackendClient(settings)
    await _swap_client(client, httpx.MockTransport(handler))
    try:
        data = await client.list_user_tasks(42, skip=5, limit=5)
        assert data["total"] == 6
        assert data["tasks"][0]["task_code"] == "00000000"
    finally:
        await client.aclose()


def test_parse_error_detail_str() -> None:
    c, m = parse_error_detail("oops")
    assert c is None
    assert m == "oops"


def test_parse_error_detail_dict() -> None:
    c, m = parse_error_detail({"message": "x", "code": "c1"})
    assert c == "c1"
    assert m == "x"


def test_task_body_for_create_omits_hold() -> None:
    body = task_body_for_create(
        telegram_id=1,
        task_type="face_swap",
        third_party_platform="runninghub",
        priority_type="default",
        input_payload={"a": 1},
    )
    assert "hold_amount" not in body
    assert body["third_party_platform"] == "runninghub"


def test_task_body_for_create_allows_server_estimated_hold() -> None:
    body = task_body_for_create(
        telegram_id=1,
        task_type="face_swap",
        third_party_platform="runninghub",
        priority_type="default",
        input_payload={"a": 1},
    )
    assert "hold_amount" not in body


@pytest.mark.asyncio
async def test_patch_user_json(settings: BotBackendSettings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == "/users/1"
        assert json.loads(request.content.decode()) == {"preferences": {"lang": "en"}}
        return httpx.Response(
            200, json={"telegram_id": 1, "preferences": {"lang": "en"}}
        )

    client = BackendClient(settings)
    await _swap_client(client, httpx.MockTransport(handler))
    try:
        data = await client.patch_user(1, {"preferences": {"lang": "en"}})
        assert data["preferences"]["lang"] == "en"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_create_trc20_recharge_payment_params(
    settings: BotBackendSettings,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/payments"
        q = request.url.params
        assert q.get("telegram_id") == "9"
        assert q.get("payment_method") == "trc20_usdt"
        assert q.get("amount_usd") == "10.5"
        return httpx.Response(
            200,
            json={
                "payment_id": "550e8400-e29b-41d4-a716-446655440000",
                "order_timeout_minutes": 12,
                "metadata": {"wallet_address": "TX", "amount_usdt": "10.500001"},
            },
        )

    client = BackendClient(settings)
    await _swap_client(client, httpx.MockTransport(handler))
    try:
        data = await client.create_trc20_recharge_payment(
            9, Decimal("10.5"), description="x"
        )
        assert data["order_timeout_minutes"] == 12
        assert data["metadata"]["wallet_address"] == "TX"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_create_plisio_recharge_payment_params(
    settings: BotBackendSettings,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/payments"
        q = request.url.params
        assert q.get("telegram_id") == "9"
        assert q.get("payment_method") == "plisio_invoice"
        assert q.get("amount_usd") == "10.5"
        return httpx.Response(
            200,
            json={
                "payment_id": "550e8400-e29b-41d4-a716-446655440000",
                "metadata": {
                    "invoice_url": "https://plisio.net/invoice/txn-1",
                    "txn_id": "txn-1",
                },
            },
        )

    client = BackendClient(settings)
    await _swap_client(client, httpx.MockTransport(handler))
    try:
        data = await client.create_plisio_recharge_payment(
            9, Decimal("10.5"), description="x"
        )
        assert data["metadata"]["txn_id"] == "txn-1"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_get_task_404(settings: BotBackendSettings) -> None:
    tid = UUID("00000000-0000-4000-8000-000000000001")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("telegram_id") == "99"
        return httpx.Response(404, json={"detail": "任务不存在或无权访问"})

    client = BackendClient(settings)
    await _swap_client(client, httpx.MockTransport(handler))
    try:
        with pytest.raises(BackendAPIError) as ei:
            await client.get_task(tid, telegram_id=99)
        assert ei.value.http_status == 404
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_upload_media_multipart(settings: BotBackendSettings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/media/uploads"
        assert request.headers.get("X-API-Key") == "secret"
        assert "multipart/form-data" in request.headers["content-type"]
        body = request.content
        assert b"face.jpg" in body
        assert b"image/jpeg" in body
        assert b"fake-image" in body
        return httpx.Response(
            200,
            json={
                "file_ref": "/app/data/uploads/2026-05-18/x.jpg",
                "filename": "face.jpg",
                "content_type": "image/jpeg",
            },
        )

    client = BackendClient(settings)
    await _swap_client(client, httpx.MockTransport(handler))
    try:
        data = await client.upload_media(
            content=b"fake-image",
            filename="face.jpg",
            content_type="image/jpeg",
        )
        assert data["file_ref"].endswith("/x.jpg")
    finally:
        await client.aclose()
