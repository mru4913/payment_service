# -*- coding: utf-8 -*-
"""POST /payments TRC20 分支与 pending 过滤。"""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

from backend.api.dependencies import payment_service_read, payment_service_write
from backend.api.main import create_api_app


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
async def test_post_trc20_returns_metadata_and_timeout(client_no_auth):
    app = client_no_auth.app
    pid = uuid4()
    pay = SimpleNamespace(
        payment_id=pid,
        telegram_id=7,
        amount_usd=Decimal("10.123456"),
        payment_method="trc20_usdt",
        status="pending",
        description="x",
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        payment_metadata={"wallet_address": "T1", "amount_usdt": "10.123456"},
    )

    class FakePay:
        async def create_trc20_usdt_payment(
            self, telegram_id, base_amount_usd, description=""
        ):
            return pay, None

    async def fake_pay():
        return FakePay()

    app.dependency_overrides[payment_service_write] = fake_pay
    try:
        with patch("backend.api.routers.payments.settings") as gs:
            gs.trc20_order_timeout_minutes = 15
            r = await client_no_auth.post(
                "/payments",
                params={
                    "telegram_id": 7,
                    "amount_usd": "10",
                    "payment_method": "trc20_usdt",
                    "description": "x",
                },
            )
        assert r.status_code == 200
        data = r.json()
        assert data["order_timeout_minutes"] == 15
        assert data["metadata"]["wallet_address"] == "T1"
        assert str(data["payment_id"]) == str(pid)
    finally:
        app.dependency_overrides.pop(payment_service_write, None)


@pytest.mark.asyncio
async def test_post_trc20_error_returns_400(client_no_auth):
    app = client_no_auth.app

    class FakePay:
        async def create_trc20_usdt_payment(
            self, telegram_id, base_amount_usd, description=""
        ):
            return None, "未配置收款地址"

    async def fake_pay():
        return FakePay()

    app.dependency_overrides[payment_service_write] = fake_pay
    try:
        r = await client_no_auth.post(
            "/payments",
            params={
                "telegram_id": 1,
                "amount_usd": "5",
                "payment_method": "trc20_usdt",
            },
        )
        assert r.status_code == 400
        assert r.json()["detail"] == "未配置收款地址"
    finally:
        app.dependency_overrides.pop(payment_service_write, None)


@pytest.mark.asyncio
async def test_post_plisio_invoice_returns_metadata(client_no_auth):
    app = client_no_auth.app
    pid = uuid4()
    pay = SimpleNamespace(
        payment_id=pid,
        telegram_id=7,
        amount_usd=Decimal("5.000000"),
        payment_method="plisio_invoice",
        status="pending",
        external_payment_id="txn-1",
        description="x",
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
        completed_at=None,
        payment_metadata={
            "txn_id": "txn-1",
            "invoice_url": "https://plisio.net/invoice/txn-1",
            "currency": "USDT_TRX",
            "source_amount_usd": "5.000000",
            "expire_minutes": 60,
        },
    )

    class FakePay:
        async def create_plisio_invoice_payment(
            self, telegram_id, amount_usd, description=""
        ):
            return pay, None

    async def fake_pay():
        return FakePay()

    app.dependency_overrides[payment_service_write] = fake_pay
    try:
        r = await client_no_auth.post(
            "/payments",
            params={
                "telegram_id": 7,
                "amount_usd": "5",
                "payment_method": "plisio_invoice",
                "description": "x",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["payment_method"] == "plisio_invoice"
        assert data["external_payment_id"] == "txn-1"
        assert data["metadata"]["invoice_url"] == "https://plisio.net/invoice/txn-1"
    finally:
        app.dependency_overrides.pop(payment_service_write, None)


@pytest.mark.asyncio
async def test_post_payment_rejects_unknown_method(client_no_auth):
    app = client_no_auth.app

    class FakePay:
        pass

    async def fake_pay():
        return FakePay()

    app.dependency_overrides[payment_service_write] = fake_pay
    try:
        r = await client_no_auth.post(
            "/payments",
            params={
                "telegram_id": 7,
                "amount_usd": "5",
                "payment_method": "manual_cash",
                "description": "x",
            },
        )
        assert r.status_code == 400
    finally:
        app.dependency_overrides.pop(payment_service_write, None)


@pytest.mark.asyncio
async def test_manual_confirm_endpoint_is_disabled(client_no_auth):
    app = client_no_auth.app

    class FakePay:
        pass

    async def fake_pay():
        return FakePay()

    app.dependency_overrides[payment_service_write] = fake_pay
    try:
        r = await client_no_auth.put(
            f"/payments/{uuid4()}/confirm",
            params={"external_payment_id": "manual-1"},
        )
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(payment_service_write, None)


@pytest.mark.asyncio
async def test_refund_endpoint_is_disabled(client_no_auth):
    app = client_no_auth.app

    class FakePay:
        async def process_refund(self, *args, **kwargs):
            raise AssertionError("refund endpoint should not mutate")

    async def fake_pay():
        return FakePay()

    app.dependency_overrides[payment_service_write] = fake_pay
    try:
        r = await client_no_auth.post(f"/payments/{uuid4()}/refund")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(payment_service_write, None)


@pytest.mark.asyncio
async def test_get_pending_passes_telegram_id(client_no_auth):
    app = client_no_auth.app
    captured: dict = {}

    class FakeRead:
        async def get_pending_payments(self, skip=0, limit=100, telegram_id=None):
            captured["telegram_id"] = telegram_id
            return []

        async def count_pending_payments(self, telegram_id=None):
            captured["count_telegram_id"] = telegram_id
            return 0

    async def fake_read():
        return FakeRead()

    app.dependency_overrides[payment_service_read] = fake_read
    try:
        r = await client_no_auth.get("/payments/pending", params={"telegram_id": 99})
        assert r.status_code == 200
        assert captured["telegram_id"] == 99
        assert captured["count_telegram_id"] == 99
        assert r.json()["returned"] == 0
        assert r.json()["total"] == 0
    finally:
        app.dependency_overrides.pop(payment_service_read, None)


@pytest.mark.asyncio
async def test_get_pending_total_and_returned(client_no_auth):
    app = client_no_auth.app
    pid = uuid4()
    row = SimpleNamespace(
        payment_id=pid,
        telegram_id=1,
        amount_usd=Decimal("1"),
        payment_method="plisio_invoice",
        status="pending",
        external_payment_id="txn-1",
        description="d",
        payment_metadata={"invoice_url": "https://plisio.net/invoice/txn-1"},
        created_at=datetime(2024, 1, 1, 0, 0, 0),
    )

    class FakeRead:
        async def get_pending_payments(self, skip=0, limit=100, telegram_id=None):
            return [row] if limit >= 1 else []

        async def count_pending_payments(self, telegram_id=None):
            return 3

    async def fake_read():
        return FakeRead()

    app.dependency_overrides[payment_service_read] = fake_read
    try:
        r = await client_no_auth.get("/payments/pending")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 3
        assert data["returned"] == 1
        assert len(data["payments"]) == 1
        assert data["payments"][0]["status"] == "pending"
        assert data["payments"][0]["external_payment_id"] == "txn-1"
        assert data["payments"][0]["metadata"]["invoice_url"].endswith("txn-1")
    finally:
        app.dependency_overrides.pop(payment_service_read, None)
