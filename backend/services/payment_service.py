#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
支付业务逻辑服务
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional, List, Dict, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from .base_service import BaseService
from ..domain.balance_transaction_types import BalanceTransactionType
from ..database.repositories import PaymentRepository
from ..database.models import Payment
from ..payments.base import PaymentRequest
from ..payments.trc20_usdt import TRC20UsdtProvider
from ..services.user_service import UserService
from ..globals import logger


class PaymentService(BaseService):
    """支付业务服务"""

    def __init__(self, db_session: AsyncSession):
        super().__init__(db_session)
        self.payment_repo = PaymentRepository(db_session)
        self.user_service = UserService(db_session)

    async def create_payment(
        self,
        telegram_id: int,
        amount_usd: Decimal,
        payment_method: str,
        description: str = "",
        payment_metadata: Optional[Dict] = None,
    ) -> Payment:
        """创建支付订单；调用方须已开启事务（如 FastAPI `get_db_write`）。"""
        await self.user_service.get_or_create_user(telegram_id)
        payment = Payment(
            telegram_id=telegram_id,
            amount_usd=amount_usd,
            payment_method=payment_method,
            description=description,
            status="pending",
            payment_metadata=payment_metadata,
        )
        return await self.payment_repo.create(payment)

    async def create_trc20_usdt_payment(
        self,
        telegram_id: int,
        base_amount_usd: Decimal,
        description: str = "",
    ) -> tuple[Optional[Payment], Optional[str]]:
        """生成唯一链上金额并创建 pending 订单；失败返回 (None, 错误说明)。"""
        provider = TRC20UsdtProvider()
        request = PaymentRequest(
            payment_id="temp",
            amount_usd=base_amount_usd,
            description=description,
            callback_url="",
        )
        result = await provider.create_unique_payment(request, self.db_session)
        if not result.success or not result.metadata:
            return None, result.error_message or "TRC20 订单创建失败"

        raw_amt = result.metadata.get("amount_usdt")
        if raw_amt is None:
            return None, "TRC20 元数据缺少 amount_usdt"
        try:
            amount_usd = Decimal(str(raw_amt))
        except (InvalidOperation, ValueError):
            return None, "TRC20 金额格式无效"

        payment = await self.create_payment(
            telegram_id=telegram_id,
            amount_usd=amount_usd,
            payment_method="trc20_usdt",
            description=description,
            payment_metadata=dict(result.metadata),
        )
        return payment, None

    async def get_payment(self, payment_id: str) -> Optional[Payment]:
        """根据支付ID获取支付详情"""
        try:
            payment_uuid = uuid.UUID(payment_id)
        except ValueError:
            return None

        return await self.payment_repo.get_by_payment_id(payment_uuid)

    async def get_payment_by_external_id(
        self, external_payment_id: str
    ) -> Optional[Payment]:
        """根据外部支付ID获取支付记录"""
        return await self.payment_repo.get_by_external_id(external_payment_id)

    async def update_payment_status(
        self, payment_id: str, status: str, external_payment_id: Optional[str] = None
    ) -> Optional[Payment]:
        """更新支付状态"""
        try:
            payment_uuid = uuid.UUID(payment_id)
        except ValueError:
            return None

        payment = await self.payment_repo.get_by_payment_id(payment_uuid)
        if not payment:
            return None

        payment.status = status
        if external_payment_id:
            payment.external_payment_id = external_payment_id

        if status == "completed" and not payment.completed_at:
            payment.completed_at = datetime.now(timezone.utc)

        return await self.payment_repo.update(
            payment,
            {
                "status": status,
                "external_payment_id": external_payment_id,
                "completed_at": payment.completed_at,
            },
        )

    async def confirm_payment(
        self, payment_id: str, external_payment_id: str
    ) -> Optional[Payment]:
        """确认支付完成并更新用户余额（与调用方同一事务）。"""
        payment = await self.get_payment(payment_id)
        if not payment:
            return None
        if payment.status == "completed":
            if payment.external_payment_id == external_payment_id:
                return payment
            logger.warning(
                "订单已完成但 external_payment_id 与回调不一致: payment_id=%s",
                payment_id,
            )
            return None
        if payment.status != "pending":
            return None

        payment.status = "completed"
        payment.external_payment_id = external_payment_id
        payment.completed_at = datetime.now(timezone.utc)

        await self.payment_repo.update(
            payment,
            {
                "status": "completed",
                "external_payment_id": external_payment_id,
                "completed_at": payment.completed_at,
            },
        )

        await self.user_service.update_balance(
            payment.telegram_id,
            payment.amount_usd,
            BalanceTransactionType.DEPOSIT,
            payment.payment_id,
            f"Payment via {payment.payment_method}",
        )

        return payment

    async def cancel_payment(self, payment_id: str) -> Optional[Payment]:
        """取消支付（仅 pending；已为 cancelled 则幂等返回）。"""
        payment = await self.get_payment(payment_id)
        if not payment:
            return None
        if payment.status == "cancelled":
            return payment
        if payment.status != "pending":
            return None
        return await self.payment_repo.update(payment, {"status": "cancelled"})

    async def fail_payment(
        self, payment_id: str, reason: str = ""
    ) -> Optional[Payment]:
        """标记支付失败"""
        payment = await self.get_payment(payment_id)
        if not payment:
            return None
        if payment.status == "failed":
            return payment
        if payment.status != "pending":
            return None

        payment.status = "failed"
        if reason:
            base = payment.description or ""
            payment.description = f"{base} - Failed: {reason}".strip()

        return await self.payment_repo.update(
            payment, {"status": "failed", "description": payment.description}
        )

    async def get_user_payments(
        self, telegram_id: int, skip: int = 0, limit: int = 20
    ) -> List[Payment]:
        """获取用户支付记录"""
        return await self.payment_repo.get_user_payments(telegram_id, skip, limit)

    async def count_user_payments(self, telegram_id: int) -> int:
        return await self.payment_repo.count_user_payments(telegram_id)

    async def get_pending_payments(
        self,
        skip: int = 0,
        limit: int = 100,
        telegram_id: Optional[int] = None,
    ) -> List[Payment]:
        """获取待处理的支付；可选按 telegram_id 过滤。"""
        return await self.payment_repo.get_pending_payments(skip, limit, telegram_id)

    async def count_pending_payments(self, telegram_id: Optional[int] = None) -> int:
        return await self.payment_repo.count_pending_payments(telegram_id)

    async def get_pending_trc20_usdt_keyset(
        self,
        cursor: Optional[Tuple[datetime, uuid.UUID]],
        limit: int,
    ) -> List[Payment]:
        """TRC20 pending FIFO 分页（keyset）。"""
        return await self.payment_repo.get_pending_trc20_usdt_keyset(cursor, limit)

    async def get_payments_by_status(
        self, status: str, skip: int = 0, limit: int = 100
    ) -> List[Payment]:
        """根据状态获取支付记录"""
        return await self.payment_repo.get_payments_by_status(status, skip, limit)

    async def count_payments_by_status(self, status: str) -> int:
        return await self.payment_repo.count_payments_by_status(status)

    async def process_refund(
        self, payment_id: str, refund_amount: Optional[Decimal] = None
    ) -> Optional[Payment]:
        """处理退款（与调用方同一事务）。"""
        payment = await self.get_payment(payment_id)
        if not payment or payment.status != "completed":
            return None

        amount = refund_amount if refund_amount is not None else payment.amount_usd
        if amount <= 0 or amount > payment.amount_usd:
            return None

        ext = payment.external_payment_id
        refund_ext = f"refund_{ext}" if ext else f"refund_{payment.payment_id}"

        refund_payment = Payment(
            telegram_id=payment.telegram_id,
            amount_usd=-amount,
            payment_method=payment.payment_method,
            description=f"Refund for payment {payment.payment_id}",
            status="completed",
            external_payment_id=refund_ext,
        )

        refund_payment = await self.payment_repo.create(refund_payment)

        await self.user_service.update_balance(
            payment.telegram_id,
            -amount,
            BalanceTransactionType.REFUND,
            refund_payment.payment_id,
            f"Refund for payment {payment.payment_id}",
        )

        return refund_payment
