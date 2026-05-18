"""UserService：总余额不得低于 balance_held。"""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from backend.database.models import User
from backend.services.user_service import BalanceBelowHeldError, UserService


def _make_user(
    balance: Decimal = Decimal("100"),
    held: Decimal = Decimal("30"),
) -> User:
    return User(
        telegram_id=1,
        is_premium=False,
        is_verified=False,
        is_scam=False,
        is_fake=False,
        is_active=True,
        balance=balance,
        balance_held=held,
        total_deposits=Decimal("100"),
        total_withdrawals=Decimal("0"),
    )


@pytest.mark.asyncio
async def test_update_balance_raises_when_new_balance_below_held():
    session = AsyncMock()
    svc = UserService(session)
    user = _make_user(balance=Decimal("10"), held=Decimal("8"))

    svc.user_repo.get_by_telegram_id = AsyncMock(return_value=user)

    with pytest.raises(BalanceBelowHeldError) as ei:
        await svc.update_balance(1, Decimal("-5"), "withdraw")
    assert ei.value.code == "balance_below_held"


@pytest.mark.asyncio
async def test_update_balance_allows_when_above_held():
    session = AsyncMock()
    svc = UserService(session)
    user = _make_user(balance=Decimal("10"), held=Decimal("8"))

    svc.user_repo.get_by_telegram_id = AsyncMock(return_value=user)
    svc.user_repo.update = AsyncMock(side_effect=lambda u, d: u)
    svc.balance_repo.create = AsyncMock()

    out = await svc.update_balance(1, Decimal("-1"), "withdraw")
    assert out is not None
    assert out.balance == Decimal("9")
