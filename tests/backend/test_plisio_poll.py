# -*- coding: utf-8 -*-
"""Plisio payment poll 单元测试。"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import backend.payments.plisio_poll as poll_mod
from backend.payments.base import PaymentStatus


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def begin(self):
        return self


def _session_maker():
    return _Session()


def _enable_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(poll_mod.settings, "payment_poll_enabled", True)
    monkeypatch.setattr(poll_mod.settings, "plisio_enabled", True)
    monkeypatch.setattr(poll_mod.settings, "plisio_api_key", "secret")
    monkeypatch.setattr(poll_mod.settings, "payment_poll_batch_size", 50)
    monkeypatch.setattr(poll_mod, "async_session_maker", _session_maker)


@pytest.mark.asyncio
async def test_plisio_poll_completed_confirms_payment(monkeypatch):
    _enable_poll(monkeypatch)
    payment_id = uuid4()
    payment = SimpleNamespace(
        payment_id=payment_id,
        external_payment_id="txn-1",
        amount_usd=Decimal("5.000000"),
    )

    class FakePaymentService:
        confirm_payment = AsyncMock(return_value=payment)

        def __init__(self, session):
            self.session = session

        async def get_pending_payments_by_method_keyset(self, *args, **kwargs):
            return [payment]

    class FakeProvider:
        async def query_payment_status(self, txn_id):
            return PaymentStatus(
                payment_id=txn_id,
                status="completed",
                external_payment_id=txn_id,
                amount_paid=Decimal("5.000000"),
                metadata={"plisio_status": "completed"},
            )

        async def close(self):
            return None

    monkeypatch.setattr(poll_mod, "PaymentService", FakePaymentService)
    monkeypatch.setattr(poll_mod, "PlisioProvider", FakeProvider)

    stats = await poll_mod.run_plisio_payment_poll_batch()

    assert stats.completed == 1
    FakePaymentService.confirm_payment.assert_awaited_once_with(
        str(payment_id),
        "txn-1",
        paid_amount=Decimal("5.000000"),
        amount_policy="at_least",
    )


@pytest.mark.asyncio
async def test_plisio_poll_completed_without_amount_fails_payment(monkeypatch):
    _enable_poll(monkeypatch)
    payment = SimpleNamespace(
        payment_id=uuid4(),
        external_payment_id="txn-1",
        amount_usd=Decimal("5.000000"),
    )

    class FakePaymentService:
        confirm_payment = AsyncMock()
        fail_payment = AsyncMock(return_value=payment)

        def __init__(self, session):
            self.session = session

        async def get_pending_payments_by_method_keyset(self, *args, **kwargs):
            return [payment]

    class FakeProvider:
        async def query_payment_status(self, txn_id):
            return PaymentStatus(
                payment_id=txn_id,
                status="completed",
                external_payment_id=txn_id,
                amount_paid=None,
                metadata={"plisio_status": "completed"},
            )

        async def close(self):
            return None

    monkeypatch.setattr(poll_mod, "PaymentService", FakePaymentService)
    monkeypatch.setattr(poll_mod, "PlisioProvider", FakeProvider)

    stats = await poll_mod.run_plisio_payment_poll_batch()

    assert stats.failed == 1
    FakePaymentService.fail_payment.assert_awaited_once()
    FakePaymentService.confirm_payment.assert_not_awaited()


@pytest.mark.asyncio
async def test_plisio_poll_cancelled_cancels_payment(monkeypatch):
    _enable_poll(monkeypatch)
    payment = SimpleNamespace(payment_id=uuid4(), external_payment_id="txn-1")

    class FakePaymentService:
        cancel_payment = AsyncMock(return_value=payment)

        def __init__(self, session):
            self.session = session

        async def get_pending_payments_by_method_keyset(self, *args, **kwargs):
            return [payment]

    class FakeProvider:
        async def query_payment_status(self, txn_id):
            return PaymentStatus(
                payment_id=txn_id,
                status="cancelled",
                metadata={"plisio_status": "expired"},
            )

        async def close(self):
            return None

    monkeypatch.setattr(poll_mod, "PaymentService", FakePaymentService)
    monkeypatch.setattr(poll_mod, "PlisioProvider", FakeProvider)

    stats = await poll_mod.run_plisio_payment_poll_batch()

    assert stats.cancelled == 1
    FakePaymentService.cancel_payment.assert_awaited_once_with(str(payment.payment_id))


@pytest.mark.asyncio
async def test_plisio_poll_disabled_skips(monkeypatch):
    monkeypatch.setattr(poll_mod.settings, "payment_poll_enabled", False)

    stats = await poll_mod.run_plisio_payment_poll_batch()

    assert stats.scanned == 0
