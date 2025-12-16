#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
支付数据访问层
"""

import uuid
from typing import Optional, List
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Payment
from .base_repository import BaseRepository


class PaymentRepository(BaseRepository[Payment]):
    """支付数据仓库"""

    def __init__(self, db_session: AsyncSession):
        super().__init__(Payment, db_session)

    async def get_by_payment_id(self, payment_id: uuid.UUID) -> Optional[Payment]:
        """根据支付ID获取支付记录"""
        stmt = select(Payment).where(Payment.payment_id == payment_id)
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_external_id(self, external_payment_id: str) -> Optional[Payment]:
        """根据外部支付ID获取支付记录"""
        stmt = select(Payment).where(Payment.external_payment_id == external_payment_id)
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_payments(
        self,
        telegram_id: int,
        skip: int = 0,
        limit: int = 20
    ) -> List[Payment]:
        """获取用户的支付记录"""
        stmt = (
            select(Payment)
            .where(Payment.telegram_id == telegram_id)
            .order_by(desc(Payment.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())

    async def get_pending_payments(
        self,
        skip: int = 0,
        limit: int = 100
    ) -> List[Payment]:
        """获取待处理的支付记录"""
        stmt = (
            select(Payment)
            .where(Payment.status == "pending")
            .order_by(Payment.created_at)
            .offset(skip)
            .limit(limit)
        )
        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())


    async def get_payments_by_status(
        self,
        status: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[Payment]:
        """根据状态获取支付记录"""
        stmt = (
            select(Payment)
            .where(Payment.status == status)
            .order_by(desc(Payment.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())
