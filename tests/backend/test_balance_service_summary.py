"""BalanceService.get_transaction_summary：算力相关类型汇总。"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.services.balance_service import BalanceService


@pytest.mark.asyncio
async def test_transaction_summary_includes_hold_and_consumption():
    session = AsyncMock()
    svc = BalanceService(session)
    txs = [
        SimpleNamespace(transaction_type="deposit", amount_usd=Decimal("10")),
        SimpleNamespace(transaction_type="hold", amount_usd=Decimal("2")),
        SimpleNamespace(transaction_type="consumption", amount_usd=Decimal("-1.5")),
        SimpleNamespace(transaction_type="hold_release", amount_usd=Decimal("0.5")),
    ]
    svc.balance_repo.get_user_transactions_in_period = AsyncMock(return_value=txs)

    s = await svc.get_transaction_summary(telegram_id=1, days=30)

    assert s["total_transactions"] == 4
    assert s["deposit_count"] == 1
    assert s["total_deposit_amount"] == Decimal("10")
    assert s["hold_count"] == 1
    assert s["total_hold_amount"] == Decimal("2")
    assert s["consumption_count"] == 1
    assert s["total_consumption_amount"] == Decimal("1.5")
    assert s["hold_release_count"] == 1
    assert s["total_hold_release_amount"] == Decimal("0.5")
