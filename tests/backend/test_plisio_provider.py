# -*- coding: utf-8 -*-
"""Plisio invoice provider 单元测试。"""

from decimal import Decimal

import httpx
import pytest

import backend.payments.plisio as plisio_mod
from backend.payments.base import PaymentRequest
from backend.payments.plisio import PlisioProvider


def _enable_plisio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plisio_mod.settings, "plisio_enabled", True)
    monkeypatch.setattr(plisio_mod.settings, "plisio_api_key", "secret")
    monkeypatch.setattr(plisio_mod.settings, "plisio_base_url", "https://api.test")
    monkeypatch.setattr(plisio_mod.settings, "plisio_recharge_currency", "USDT_TRX")
    monkeypatch.setattr(plisio_mod.settings, "plisio_invoice_expire_minutes", 60)


@pytest.mark.asyncio
async def test_create_invoice_success_sends_expected_params(monkeypatch):
    _enable_plisio(monkeypatch)
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/invoices/new"
        seen.update(dict(request.url.params.multi_items()))
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "txn_id": "txn-1",
                    "invoice_url": "https://plisio.net/invoice/txn-1",
                    "invoice_total_sum": "5.000000",
                    "psys_cid": "USDT_TRX",
                },
            },
        )

    provider = PlisioProvider()
    provider._http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.test",
    )
    try:
        result = await provider.create_payment(
            PaymentRequest(
                payment_id="local-1",
                amount_usd=Decimal("5"),
                description="Top up",
                callback_url="",
            )
        )
    finally:
        await provider.close()

    assert result.success is True
    assert result.external_payment_id == "txn-1"
    assert result.metadata["invoice_url"] == "https://plisio.net/invoice/txn-1"
    assert seen["source_currency"] == "USD"
    assert seen["source_amount"] == "5"
    assert seen["order_number"] == "local-1"
    assert seen["currency"] == "USDT_TRX"
    assert seen["allowed_psys_cids"] == "USDT_TRX"
    assert seen["api_key"] == "secret"


@pytest.mark.asyncio
async def test_create_invoice_error_returns_failure(monkeypatch):
    _enable_plisio(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "status": "error",
                "data": {"message": "bad invoice", "code": 103},
            },
        )

    provider = PlisioProvider()
    provider._http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.test",
    )
    try:
        result = await provider.create_payment(
            PaymentRequest(
                payment_id="local-1",
                amount_usd=Decimal("5"),
                description="Top up",
                callback_url="",
            )
        )
    finally:
        await provider.close()

    assert result.success is False
    assert result.error_message == "bad invoice"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("plisio_status", "local_status"),
    [
        ("completed", "completed"),
        ("new", "pending"),
        ("pending", "pending"),
        ("pending internal", "pending"),
        ("expired", "cancelled"),
        ("cancelled", "cancelled"),
        ("cancelled duplicate", "cancelled"),
        ("mismatch", "failed"),
        ("error", "failed"),
    ],
)
async def test_query_invoice_status_mapping(
    monkeypatch,
    plisio_status,
    local_status,
):
    _enable_plisio(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/operations/txn-1"
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "id": "txn-1",
                    "status": plisio_status,
                    "actual_invoice_sum": "5.000000",
                    "source_amount": "9.000000",
                },
            },
        )

    provider = PlisioProvider()
    provider._http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.test",
    )
    try:
        status = await provider.query_payment_status("txn-1")
    finally:
        await provider.close()

    assert status.status == local_status
    assert status.external_payment_id == "txn-1"
    assert status.amount_paid == Decimal("5.000000")


@pytest.mark.asyncio
async def test_query_invoice_does_not_treat_source_amount_as_paid(monkeypatch):
    _enable_plisio(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/operations/txn-1"
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "id": "txn-1",
                    "status": "completed",
                    "source_amount": "5.000000",
                },
            },
        )

    provider = PlisioProvider()
    provider._http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.test",
    )
    try:
        status = await provider.query_payment_status("txn-1")
    finally:
        await provider.close()

    assert status.status == "completed"
    assert status.amount_paid is None
