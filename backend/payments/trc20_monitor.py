#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
TRC20 USDT 链上到账监控

后台轮询 TronScan，将链上交易按金额匹配 pending 订单，
匹配成功后自动确认支付并充值用户余额。
"""

import asyncio
from collections import OrderedDict
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import httpx

from .trc20_usdt import TRC20UsdtProvider
from ..config import Settings
from ..database.session import async_session_maker
from ..services.payment_service import PaymentService
from ..globals import logger

_MAX_SEEN_TX_IDS = 5000


class TRC20Monitor:
    """TRC20 USDT 到账监控后台任务"""

    def __init__(self, config: Settings):
        self.config = config
        self.provider = TRC20UsdtProvider()
        self.check_interval = config.trc20_check_interval
        self.order_timeout = timedelta(minutes=config.trc20_order_timeout_minutes)
        self._seen_tx_ids: OrderedDict[str, None] = OrderedDict()
        self._running = False

    async def start(self):
        """启动监控主循环"""
        self._running = True
        logger.info(
            f"TRC20 监控已启动 | 地址: {self.config.trc20_wallet_address} | "
            f"间隔: {self.check_interval}s"
        )
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"TRC20 监控轮询异常: {e}", exc_info=True)
            await asyncio.sleep(self.check_interval)

    async def stop(self):
        self._running = False
        await self.provider.close()

    async def _tick(self):
        """单次轮询：检查到账 + 清理过期订单"""
        await self._check_payments()
        await self._cancel_expired_orders()

    async def _check_payments(self):
        transfers = await self.provider.fetch_recent_transfers()
        if not transfers:
            return

        wallet = (self.config.trc20_wallet_address or "").lower()

        for tx in transfers:
            tx_id = tx.get("transaction_id")
            if not tx_id or tx_id in self._seen_tx_ids:
                continue

            to_addr = (tx.get("to_address") or "").lower()
            if to_addr != wallet:
                continue

            raw_value = tx.get("value", "0")
            amount = Decimal(str(raw_value)) / Decimal("1000000")
            if amount <= 0:
                continue

            from_addr = tx.get("from_address", "")
            self._seen_tx_ids[tx_id] = None

            while len(self._seen_tx_ids) > _MAX_SEEN_TX_IDS:
                self._seen_tx_ids.popitem(last=False)

            await self._try_match_order(tx_id, amount, from_addr)

    async def _try_match_order(self, tx_id: str, amount: Decimal, from_addr: str):
        """按金额匹配一笔 pending 的 trc20_usdt 订单（FIFO + keyset 全量扫描）。"""
        async with async_session_maker() as session:
            svc = PaymentService(session)
            if await svc.get_payment_by_external_id(tx_id):
                return

        batch_size = self.config.trc20_pending_scan_batch_size
        max_batches = self.config.trc20_pending_scan_max_batches
        cursor = None
        matched_pid: str | None = None
        matched_tid: int | None = None

        for _ in range(max_batches):
            async with async_session_maker() as session:
                svc = PaymentService(session)
                batch = await svc.get_pending_trc20_usdt_keyset(cursor, batch_size)

            for p in batch:
                if p.amount_usd == amount:
                    matched_pid = str(p.payment_id)
                    matched_tid = p.telegram_id
                    break

            if matched_pid:
                break
            if not batch or len(batch) < batch_size:
                break
            last = batch[-1]
            cursor = (last.created_at, last.payment_id)

        if not matched_pid or matched_tid is None:
            logger.info(
                f"TRC20 到账未匹配订单 | {amount} USDT | "
                f"tx={tx_id[:16]}… | from={from_addr}"
            )
            return

        async with async_session_maker() as session:
            async with session.begin():
                svc = PaymentService(session)
                payment = await svc.confirm_payment(
                    payment_id=matched_pid,
                    external_payment_id=tx_id,
                )

        if payment:
            logger.info(
                f"TRC20 订单匹配成功 | {amount} USDT | order={matched_pid} | tx={tx_id}"
            )
            await self._notify_user(matched_tid, amount, tx_id)
        else:
            logger.warning(f"TRC20 confirm_payment 失败 | order={matched_pid}")

    async def _cancel_expired_orders(self):
        """取消超时未支付的 trc20_usdt 订单（keyset 扫描全部 pending）。"""
        cutoff = datetime.now(timezone.utc) - self.order_timeout
        batch_size = self.config.trc20_pending_scan_batch_size
        max_batches = self.config.trc20_pending_scan_max_batches

        expired_ids: list[str] = []
        cursor = None
        for _ in range(max_batches):
            async with async_session_maker() as session:
                svc = PaymentService(session)
                batch = await svc.get_pending_trc20_usdt_keyset(cursor, batch_size)

            if not batch:
                break

            for p in batch:
                created = p.created_at
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created < cutoff:
                    expired_ids.append(str(p.payment_id))

            if len(batch) < batch_size:
                break
            last = batch[-1]
            cursor = (last.created_at, last.payment_id)

        for pid in expired_ids:
            try:
                async with async_session_maker() as session:
                    async with session.begin():
                        svc = PaymentService(session)
                        await svc.cancel_payment(pid)
                    logger.info(f"TRC20 订单超时取消 | order={pid}")
            except Exception as e:
                logger.error(f"TRC20 取消订单失败 | order={pid} | {e}")

    async def _notify_user(self, telegram_id: int, amount: Decimal, tx_id: str):
        """通过 Telegram Bot API 通知用户到账"""
        token = self.config.telegram_bot_token
        if not token:
            return
        text = (
            f"✅ 充值到账通知\n\n金额: {amount} USDT\n交易ID: {tx_id}\n余额已自动更新"
        )
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    url,
                    json={
                        "chat_id": telegram_id,
                        "text": text,
                        "parse_mode": "HTML",
                    },
                )
        except Exception as e:
            logger.error(f"TRC20 到账通知发送失败: {e}")
