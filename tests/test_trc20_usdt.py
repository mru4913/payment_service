"""TRC20UsdtProvider 单元测试"""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from backend.payments.trc20_usdt import TRC20UsdtProvider, _TAIL_DIGITS
from backend.payments.base import PaymentRequest


class TestMakeUniqueAmount:
    def test_preserves_integer_part(self):
        amount = TRC20UsdtProvider._make_unique_amount(Decimal("10"))
        assert int(amount) == 10

    def test_preserves_integer_part_large(self):
        amount = TRC20UsdtProvider._make_unique_amount(Decimal("999"))
        assert int(amount) == 999

    def test_drops_original_fraction(self):
        amount = TRC20UsdtProvider._make_unique_amount(Decimal("10.5"))
        assert int(amount) == 10

    def test_six_decimal_precision(self):
        amount = TRC20UsdtProvider._make_unique_amount(Decimal("1"))
        assert amount == amount.quantize(Decimal("0.000001"))

    def test_nonzero_tail(self):
        for _ in range(50):
            amount = TRC20UsdtProvider._make_unique_amount(Decimal("5"))
            frac = amount - int(amount)
            assert frac > 0

    def test_tail_within_range(self):
        for _ in range(100):
            amount = TRC20UsdtProvider._make_unique_amount(Decimal("1"))
            frac = amount - int(amount)
            max_frac = Decimal(10**_TAIL_DIGITS - 1) / Decimal(10**_TAIL_DIGITS)
            assert Decimal("0.000001") <= frac <= max_frac

    def test_zero_base(self):
        amount = TRC20UsdtProvider._make_unique_amount(Decimal("0"))
        assert int(amount) == 0
        assert amount > 0


class TestCreatePayment:
    @pytest.mark.asyncio
    async def test_no_wallet_returns_failure(self):
        provider = TRC20UsdtProvider()
        provider.wallet_address = ""
        req = PaymentRequest(
            payment_id="test-id",
            amount_usd=Decimal("10"),
            description="test",
            callback_url="",
        )
        result = await provider.create_payment(req)
        assert result.success is False
        assert "未配置" in result.error_message

    @pytest.mark.asyncio
    async def test_success_returns_metadata(self):
        provider = TRC20UsdtProvider()
        provider.wallet_address = "TTestAddress123"
        req = PaymentRequest(
            payment_id="test-id",
            amount_usd=Decimal("10"),
            description="test",
            callback_url="",
        )
        result = await provider.create_payment(req)
        assert result.success is True
        assert result.metadata["wallet_address"] == "TTestAddress123"
        assert result.metadata["network"] == "TRC20"
        assert "amount_usdt" in result.metadata
        usdt = Decimal(result.metadata["amount_usdt"])
        assert int(usdt) == 10

    @pytest.mark.asyncio
    async def test_create_unique_payment_no_wallet(self):
        provider = TRC20UsdtProvider()
        provider.wallet_address = ""
        req = PaymentRequest(
            payment_id="test-id",
            amount_usd=Decimal("10"),
            description="test",
            callback_url="",
        )
        mock_session = AsyncMock()
        result = await provider.create_unique_payment(req, mock_session)
        assert result.success is False


class TestFetchRecentTransfers:
    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self):
        provider = TRC20UsdtProvider()
        provider.wallet_address = "TTest"
        provider._http_client = AsyncMock()
        provider._http_client.is_closed = False
        provider._http_client.get = AsyncMock(side_effect=Exception("network"))
        result = await provider.fetch_recent_transfers()
        assert result == []
