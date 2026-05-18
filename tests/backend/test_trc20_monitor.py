"""TRC20Monitor 单元测试"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from backend.payments.trc20_monitor import TRC20Monitor, _MAX_SEEN_TX_IDS


def _make_config(**overrides):
    cfg = MagicMock()
    cfg.trc20_wallet_address = "TWalletAddr"
    cfg.trc20_check_interval = 15
    cfg.trc20_order_timeout_minutes = 15
    cfg.trc20_pending_scan_batch_size = 200
    cfg.trc20_pending_scan_max_batches = 100
    cfg.telegram_bot_token = None
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _mock_db_session_with_begin():
    """与生产代码一致：`async with session` 且写路径上 `async with session.begin()`。"""
    session = AsyncMock()
    begin_cm = MagicMock()
    begin_cm.__aenter__ = AsyncMock(return_value=None)
    begin_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=begin_cm)
    return session


class TestCheckPayments:
    @pytest.mark.asyncio
    async def test_skips_already_seen_tx(self):
        monitor = TRC20Monitor(_make_config())
        monitor._seen_tx_ids["tx_already"] = None
        monitor.provider = AsyncMock()
        monitor.provider.fetch_recent_transfers = AsyncMock(
            return_value=[
                {
                    "transaction_id": "tx_already",
                    "to_address": "TWalletAddr",
                    "value": 10_000_000,
                }
            ]
        )
        monitor._try_match_order = AsyncMock()

        await monitor._check_payments()
        monitor._try_match_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_wrong_address(self):
        monitor = TRC20Monitor(_make_config())
        monitor.provider = AsyncMock()
        monitor.provider.fetch_recent_transfers = AsyncMock(
            return_value=[
                {"transaction_id": "tx1", "to_address": "TOther", "value": 10_000_000}
            ]
        )
        monitor._try_match_order = AsyncMock()

        await monitor._check_payments()
        monitor._try_match_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_parses_amount_correctly(self):
        monitor = TRC20Monitor(_make_config())
        monitor.provider = AsyncMock()
        monitor.provider.fetch_recent_transfers = AsyncMock(
            return_value=[
                {
                    "transaction_id": "tx_new",
                    "to_address": "TWalletAddr",
                    "value": 10_500_000,
                    "from_address": "TSender",
                }
            ]
        )
        monitor._try_match_order = AsyncMock()

        await monitor._check_payments()
        monitor._try_match_order.assert_called_once_with(
            "tx_new", Decimal("10.5"), "TSender"
        )

    @pytest.mark.asyncio
    async def test_skips_zero_amount(self):
        monitor = TRC20Monitor(_make_config())
        monitor.provider = AsyncMock()
        monitor.provider.fetch_recent_transfers = AsyncMock(
            return_value=[
                {"transaction_id": "tx0", "to_address": "TWalletAddr", "value": 0}
            ]
        )
        monitor._try_match_order = AsyncMock()

        await monitor._check_payments()
        monitor._try_match_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_seen_tx_lru_eviction(self):
        monitor = TRC20Monitor(_make_config())
        for i in range(_MAX_SEEN_TX_IDS):
            monitor._seen_tx_ids[f"old_{i}"] = None

        monitor.provider = AsyncMock()
        monitor.provider.fetch_recent_transfers = AsyncMock(
            return_value=[
                {
                    "transaction_id": "tx_new_evict",
                    "to_address": "TWalletAddr",
                    "value": 1_000_000,
                    "from_address": "T",
                }
            ]
        )
        monitor._try_match_order = AsyncMock()

        await monitor._check_payments()
        assert len(monitor._seen_tx_ids) == _MAX_SEEN_TX_IDS
        assert "tx_new_evict" in monitor._seen_tx_ids
        assert "old_0" not in monitor._seen_tx_ids


class TestCancelExpiredOrders:
    @pytest.mark.asyncio
    async def test_cancels_expired_trc20_orders(self):
        monitor = TRC20Monitor(_make_config(trc20_order_timeout_minutes=15))

        old_time = datetime.now(timezone.utc) - timedelta(minutes=20)
        mock_payment = MagicMock()
        mock_payment.payment_method = "trc20_usdt"
        mock_payment.created_at = old_time
        mock_payment.payment_id = "uuid-expired"

        mock_svc = AsyncMock()
        mock_svc.get_pending_trc20_usdt_keyset = AsyncMock(return_value=[mock_payment])
        mock_svc.cancel_payment = AsyncMock()

        mock_session = _mock_db_session_with_begin()

        with patch("backend.payments.trc20_monitor.async_session_maker") as mock_sm:
            mock_sm.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sm.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch(
                "backend.payments.trc20_monitor.PaymentService", return_value=mock_svc
            ):
                await monitor._cancel_expired_orders()

        assert mock_svc.cancel_payment.call_count >= 1

    @pytest.mark.asyncio
    async def test_skips_non_trc20_orders(self):
        monitor = TRC20Monitor(_make_config())

        mock_svc = AsyncMock()
        mock_svc.get_pending_trc20_usdt_keyset = AsyncMock(return_value=[])
        mock_svc.cancel_payment = AsyncMock()
        mock_session = AsyncMock()

        with patch("backend.payments.trc20_monitor.async_session_maker") as mock_sm:
            mock_sm.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sm.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch(
                "backend.payments.trc20_monitor.PaymentService", return_value=mock_svc
            ):
                await monitor._cancel_expired_orders()

        mock_svc.cancel_payment.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_naive_datetime(self):
        """created_at 无时区信息时应正确处理"""
        monitor = TRC20Monitor(_make_config(trc20_order_timeout_minutes=15))

        old_time = (datetime.now(timezone.utc) - timedelta(minutes=20)).replace(
            tzinfo=None
        )
        mock_payment = MagicMock()
        mock_payment.payment_method = "trc20_usdt"
        mock_payment.created_at = old_time  # naive datetime
        mock_payment.payment_id = "uuid-naive"

        mock_svc = AsyncMock()
        mock_svc.get_pending_trc20_usdt_keyset = AsyncMock(return_value=[mock_payment])
        mock_svc.cancel_payment = AsyncMock()
        mock_session = _mock_db_session_with_begin()

        with patch("backend.payments.trc20_monitor.async_session_maker") as mock_sm:
            mock_sm.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sm.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch(
                "backend.payments.trc20_monitor.PaymentService", return_value=mock_svc
            ):
                await monitor._cancel_expired_orders()

        assert mock_svc.cancel_payment.call_count >= 1
