# -*- coding: utf-8 -*-
"""PaymentService.confirm_payment 幂等与金额校验。"""

from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from backend.database.models import Payment
from backend.services.payment_service import PaymentService


def _payment(status: str = "pending", external_id: str | None = None) -> Payment:
    return Payment(
        payment_id=uuid4(),
        telegram_id=1,
        amount_usd=Decimal("5.000000"),
        payment_method="plisio_invoice",
        status=status,
        external_payment_id=external_id,
    )


@pytest.mark.asyncio
async def test_confirm_payment_updates_balance_only_after_cas_hit():
    svc = PaymentService(AsyncMock())
    pending = _payment()
    completed = _payment(status="completed", external_id="txn-1")
    completed.payment_id = pending.payment_id

    svc.payment_repo.get_by_payment_id = AsyncMock(return_value=pending)
    svc.payment_repo.get_by_method_external_id = AsyncMock(return_value=None)
    svc.payment_repo.confirm_pending_payment = AsyncMock(return_value=completed)
    svc.user_service.update_balance = AsyncMock()

    out = await svc.confirm_payment(
        str(pending.payment_id),
        "txn-1",
        paid_amount=Decimal("5.000000"),
        amount_policy="exact",
    )

    assert out is completed
    svc.user_service.update_balance.assert_awaited_once()


@pytest.mark.asyncio
async def test_confirm_payment_cas_miss_is_idempotent_without_balance_update():
    svc = PaymentService(AsyncMock())
    pending = _payment()
    completed = _payment(status="completed", external_id="txn-1")
    completed.payment_id = pending.payment_id

    svc.payment_repo.get_by_payment_id = AsyncMock(side_effect=[pending, completed])
    svc.payment_repo.get_by_method_external_id = AsyncMock(return_value=None)
    svc.payment_repo.confirm_pending_payment = AsyncMock(return_value=None)
    svc.user_service.update_balance = AsyncMock()

    out = await svc.confirm_payment(str(pending.payment_id), "txn-1")

    assert out is completed
    svc.user_service.update_balance.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirm_payment_rejects_amount_mismatch_before_cas():
    svc = PaymentService(AsyncMock())
    pending = _payment()

    svc.payment_repo.get_by_payment_id = AsyncMock(return_value=pending)
    svc.payment_repo.confirm_pending_payment = AsyncMock()
    svc.user_service.update_balance = AsyncMock()

    out = await svc.confirm_payment(
        str(pending.payment_id),
        "txn-1",
        paid_amount=Decimal("4.990000"),
        amount_policy="at_least",
    )

    assert out is None
    svc.payment_repo.confirm_pending_payment.assert_not_awaited()
    svc.user_service.update_balance.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirm_payment_rejects_duplicate_external_payment_id():
    svc = PaymentService(AsyncMock())
    pending = _payment()
    duplicate = _payment(status="completed", external_id="txn-1")

    svc.payment_repo.get_by_payment_id = AsyncMock(return_value=pending)
    svc.payment_repo.get_by_method_external_id = AsyncMock(return_value=duplicate)
    svc.payment_repo.confirm_pending_payment = AsyncMock()
    svc.user_service.update_balance = AsyncMock()

    out = await svc.confirm_payment(str(pending.payment_id), "txn-1")

    assert out is None
    svc.payment_repo.confirm_pending_payment.assert_not_awaited()
    svc.user_service.update_balance.assert_not_awaited()
