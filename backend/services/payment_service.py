#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
支付业务逻辑服务
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List, Dict
from sqlalchemy.ext.asyncio import AsyncSession

from .base_service import BaseService
from ..database.repositories import PaymentRepository
from ..database.models import Payment
from ..services.user_service import UserService


class PaymentService(BaseService):
    """支付业务服务"""

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session
        self.payment_repo = PaymentRepository(db_session)
        self.user_service = UserService(db_session)

    async def create_payment(
        self,
        telegram_id: int,
        amount_usd: Decimal,
        payment_method: str,
        description: str = "",
        metadata: Optional[Dict] = None
    ) -> Payment:
        """创建支付订单"""
        # 确保用户存在
        await self.user_service.get_or_create_user(telegram_id)

        # 创建支付记录
        payment = Payment(
            telegram_id=telegram_id,
            amount_usd=amount_usd,
            payment_method=payment_method,
            description=description,
            status="pending",
            metadata=metadata
        )
        return await self.payment_repo.create(payment)

    async def get_payment(self, payment_id: str) -> Optional[Payment]:
        """根据支付ID获取支付详情"""
        try:
            payment_uuid = uuid.UUID(payment_id)
        except ValueError:
            return None

        return await self.payment_repo.get_by_payment_id(payment_uuid)

    async def get_payment_by_external_id(
        self,
        external_payment_id: str
    ) -> Optional[Payment]:
        """根据外部支付ID获取支付记录"""
        return await self.payment_repo.get_by_external_id(external_payment_id)

    async def update_payment_status(
        self,
        payment_id: str,
        status: str,
        external_payment_id: Optional[str] = None
    ) -> Optional[Payment]:
        """更新支付状态"""

        async def _update_status():
            try:
                payment_uuid = uuid.UUID(payment_id)
            except ValueError:
                return None

            payment = await self.payment_repo.get_by_payment_id(payment_uuid)
            if not payment:
                return None

            # 更新支付状态和相关字段
            payment.status = status
            if external_payment_id:
                payment.external_payment_id = external_payment_id

            if status == "completed" and not payment.completed_at:
                payment.completed_at = datetime.now(timezone.utc)

            # 使用Repository的update方法
            return await self.payment_repo.update(payment, {
                "status": status,
                "external_payment_id": external_payment_id,
                "completed_at": payment.completed_at
            })

        return await self.execute_in_transaction(_update_status)

    async def confirm_payment(
        self,
        payment_id: str,
        external_payment_id: str
    ) -> Optional[Payment]:
        """确认支付完成并更新用户余额 - 原子性操作"""

        async def _confirm_payment():
            # 获取支付记录
            payment = await self.get_payment(payment_id)
            if not payment or payment.status != "pending":
                return None

            # 更新支付状态
            payment.status = "completed"
            payment.external_payment_id = external_payment_id
            payment.completed_at = datetime.now(timezone.utc)

            await self.payment_repo.update(payment, {
                "status": "completed",
                "external_payment_id": external_payment_id,
                "completed_at": payment.completed_at
            })

            # 更新用户余额（在同一事务中）
            await self.user_service.update_balance(
                payment.telegram_id,
                payment.amount_usd,
                "deposit",
                str(payment.payment_id),
                f"Payment via {payment.payment_method}"
            )

            return payment

        return await self.execute_in_transaction(_confirm_payment)

    async def cancel_payment(self, payment_id: str) -> Optional[Payment]:
        """取消支付"""
        return await self.update_payment_status(payment_id, "cancelled")

    async def fail_payment(
        self,
        payment_id: str,
        reason: str = ""
    ) -> Optional[Payment]:
        """标记支付失败"""

        async def _fail_payment():
            payment = await self.get_payment(payment_id)
            if not payment:
                return None

            payment.status = "failed"
            if reason:
                payment.description = f"{payment.description} - Failed: {reason}"

            return await self.payment_repo.update(payment, {
                "status": "failed",
                "description": payment.description
            })

        return await self.execute_in_transaction(_fail_payment)

    async def get_user_payments(
        self,
        telegram_id: int,
        skip: int = 0,
        limit: int = 20
    ) -> List[Payment]:
        """获取用户支付记录"""
        return await self.payment_repo.get_user_payments(telegram_id, skip, limit)

    async def get_pending_payments(
        self,
        skip: int = 0,
        limit: int = 100
    ) -> List[Payment]:
        """获取待处理的支付"""
        return await self.payment_repo.get_pending_payments(skip, limit)

    async def get_payments_by_status(
        self,
        status: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[Payment]:
        """根据状态获取支付记录"""
        return await self.payment_repo.get_payments_by_status(status, skip, limit)

    async def process_refund(
        self,
        payment_id: str,
        refund_amount: Optional[Decimal] = None
    ) -> Optional[Payment]:
        """处理退款 - 原子性操作"""

        async def _process_refund():
            nonlocal refund_amount
            payment = await self.get_payment(payment_id)
            if not payment or payment.status != "completed":
                return None

            refund_amount = refund_amount or payment.amount_usd

            # 创建退款记录
            refund_payment = Payment(
                telegram_id=payment.telegram_id,
                amount_usd=-refund_amount,  # 负数表示退款
                payment_method=payment.payment_method,
                description=f"Refund for payment {payment.payment_id}",
                status="completed",
                external_payment_id=f"refund_{payment.external_payment_id}"
            )

            refund_payment = await self.payment_repo.create(refund_payment)

            # 更新用户余额（在同一事务中）
            await self.user_service.update_balance(
                payment.telegram_id,
                -refund_amount,
                "refund",
                str(refund_payment.payment_id),
                f"Refund for payment {payment.payment_id}"
            )

            return refund_payment

        return await self.execute_in_transaction(_process_refund)
