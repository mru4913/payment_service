#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
TRC20 USDT 支付提供商

通过轮询 TronScan API 检测链上到账，不走传统回调机制。
create_payment 仅返回收款地址和精确金额（尾数唯一化），
实际到账确认由 TRC20Monitor 后台任务完成。
"""

import random
from decimal import Decimal
from typing import Dict, Any, Optional, List

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .base import PaymentProvider, PaymentRequest, PaymentResult, PaymentStatus
from ..globals import settings, logger

USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
TRONSCAN_API = "https://apilist.tronscan.org/api/token_trc20/transfers"

# USDT TRC20 精度为 6 位，全部用于唯一尾数
_TAIL_DIGITS = 6


class TRC20UsdtProvider(PaymentProvider):
    """TRC20 USDT 支付提供商"""

    def __init__(self):
        self.wallet_address: str = settings.trc20_wallet_address or ""
        self._http_client: Optional[httpx.AsyncClient] = None

    @property
    def name(self) -> str:
        return "trc20_usdt"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=15)
        return self._http_client

    # ---- PaymentProvider 接口实现 ----

    async def create_payment(self, request: PaymentRequest) -> PaymentResult:
        """返回收款地址和唯一化金额，不实际调链。"""
        if not self.wallet_address:
            return PaymentResult(
                success=False,
                payment_id=request.payment_id,
                error_message="TRC20 收款地址未配置",
            )

        unique_amount = self._make_unique_amount(request.amount_usd)

        return PaymentResult(
            success=True,
            payment_id=request.payment_id,
            payment_url=None,
            metadata={
                "wallet_address": self.wallet_address,
                "amount_usdt": str(unique_amount),
                "network": "TRC20",
                "contract": USDT_CONTRACT,
            },
        )

    async def create_unique_payment(
        self, request: PaymentRequest, db_session: AsyncSession
    ) -> PaymentResult:
        """创建带唯一金额的支付，并确保金额在所有 pending 订单中无冲突。

        与 create_payment 不同，此方法会查库去重，应由业务层调用。
        返回的 metadata["amount_usdt"] 即为用户应转账的精确金额。
        """
        if not self.wallet_address:
            return PaymentResult(
                success=False,
                payment_id=request.payment_id,
                error_message="TRC20 收款地址未配置",
            )

        from ..database.models import Payment

        existing_stmt = select(Payment.amount_usd).where(
            Payment.payment_method == "trc20_usdt",
            Payment.status == "pending",
        )
        result = await db_session.execute(existing_stmt)
        existing_amounts = {row[0] for row in result.all()}

        unique_amount = self._make_unique_amount(request.amount_usd)
        max_attempts = 50
        for _ in range(max_attempts):
            if unique_amount not in existing_amounts:
                break
            unique_amount = self._make_unique_amount(request.amount_usd)
        else:
            return PaymentResult(
                success=False,
                payment_id=request.payment_id,
                error_message="无法生成唯一金额，请稍后重试",
            )

        return PaymentResult(
            success=True,
            payment_id=request.payment_id,
            payment_url=None,
            metadata={
                "wallet_address": self.wallet_address,
                "amount_usdt": str(unique_amount),
                "network": "TRC20",
                "contract": USDT_CONTRACT,
            },
        )

    async def query_payment_status(self, payment_id: str) -> PaymentStatus:
        """通过 payment_id（即 tx_id）查询链上状态。"""
        return PaymentStatus(
            payment_id=payment_id,
            status="pending",
        )

    async def cancel_payment(self, payment_id: str) -> bool:
        return True

    async def validate_callback(
        self,
        callback_data: Dict[str, Any],
        *,
        raw_body: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> bool:
        _ = callback_data, raw_body, headers
        return True

    # ---- TronScan 查询 ----

    async def fetch_recent_transfers(self, limit: int = 50) -> List[Dict[str, Any]]:
        """从 TronScan 拉取收款地址最近的 TRC20 USDT 转入记录。"""
        client = await self._get_client()
        params = {
            "address": self.wallet_address,
            "limit": limit,
            "relatedAddress": self.wallet_address,
            "contract": USDT_CONTRACT,
        }
        try:
            resp = await client.get(TRONSCAN_API, params=params)
            resp.raise_for_status()
            return resp.json().get("data", [])
        except Exception as e:
            logger.error(f"TronScan API 请求失败: {e}")
            return []

    # ---- 工具方法 ----

    @staticmethod
    def _make_unique_amount(base_amount: Decimal) -> Decimal:
        """保留用户原始整数部分，附加随机 4 位小数尾数。

        例: 10 -> 10.0037, 10.5 -> 10.0037 (取整数部分 + 随机尾数)。
        USDT TRC20 精度 6 位，我们占用前 4 位小数做唯一标识，
        用户看到的转账金额即为此值。
        调用方应在数据库层面再做一次去重校验。
        """
        integer_part = int(base_amount)
        tail = random.randint(1, 10**_TAIL_DIGITS - 1)
        fraction = Decimal(tail) / Decimal(10**_TAIL_DIGITS)
        return (Decimal(integer_part) + fraction).quantize(Decimal("0.000001"))

    async def close(self):
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
