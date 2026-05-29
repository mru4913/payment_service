#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
支付数据访问层
"""

import uuid
from datetime import datetime
from typing import List, Optional, Tuple
from sqlalchemy import and_, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

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

    async def confirm_pending_payment(
        self,
        payment_id: uuid.UUID,
        *,
        external_payment_id: str,
        completed_at: datetime,
    ) -> Optional[Payment]:
        """原子确认 pending 订单；未命中表示已被其它流程处理。"""
        other = aliased(Payment)
        duplicate_external = (
            select(other.payment_id)
            .where(
                other.payment_method == Payment.payment_method,
                other.external_payment_id == external_payment_id,
                other.payment_id != payment_id,
            )
            .exists()
        )
        stmt = (
            update(Payment)
            .where(
                Payment.payment_id == payment_id,
                Payment.status == "pending",
                ~duplicate_external,
            )
            .values(
                status="completed",
                external_payment_id=external_payment_id,
                completed_at=completed_at,
            )
            .returning(Payment)
        )
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_external_id(self, external_payment_id: str) -> Optional[Payment]:
        """根据外部支付ID获取支付记录"""
        stmt = select(Payment).where(Payment.external_payment_id == external_payment_id)
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_method_external_id(
        self,
        payment_method: str,
        external_payment_id: str,
    ) -> Optional[Payment]:
        """根据支付方式 + 外部支付 ID 获取支付记录。"""
        stmt = select(Payment).where(
            Payment.payment_method == payment_method,
            Payment.external_payment_id == external_payment_id,
        )
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_payments(
        self, telegram_id: int, skip: int = 0, limit: int = 20
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

    async def count_user_payments(self, telegram_id: int) -> int:
        """该用户支付记录总条数（与 ``get_user_payments`` 筛选一致）。"""
        stmt = (
            select(func.count())
            .select_from(Payment)
            .where(Payment.telegram_id == telegram_id)
        )
        result = await self.db_session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def get_pending_payments(
        self,
        skip: int = 0,
        limit: int = 100,
        telegram_id: Optional[int] = None,
    ) -> List[Payment]:
        """获取待处理的支付记录；可选按 telegram_id 过滤。"""
        stmt = select(Payment).where(Payment.status == "pending")
        if telegram_id is not None:
            stmt = stmt.where(Payment.telegram_id == telegram_id)
        stmt = stmt.order_by(Payment.created_at).offset(skip).limit(limit)
        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())

    async def count_pending_payments(self, telegram_id: Optional[int] = None) -> int:
        """pending 总条数；可选 ``telegram_id`` 与列表接口一致。"""
        stmt = (
            select(func.count()).select_from(Payment).where(Payment.status == "pending")
        )
        if telegram_id is not None:
            stmt = stmt.where(Payment.telegram_id == telegram_id)
        result = await self.db_session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def get_pending_trc20_usdt_keyset(
        self,
        cursor: Optional[Tuple[datetime, uuid.UUID]],
        limit: int,
    ) -> List[Payment]:
        """pending TRC20：按 created_at、payment_id 升序（FIFO），keyset 分页。"""
        return await self.get_pending_by_method_keyset("trc20_usdt", cursor, limit)

    async def get_pending_by_method_keyset(
        self,
        payment_method: str,
        cursor: Optional[Tuple[datetime, uuid.UUID]],
        limit: int,
    ) -> List[Payment]:
        """指定支付方式 pending：按 created_at、payment_id 升序（FIFO）。"""
        stmt = select(Payment).where(
            Payment.status == "pending",
            Payment.payment_method == payment_method,
        )
        if cursor is not None:
            after_created, after_id = cursor
            stmt = stmt.where(
                or_(
                    Payment.created_at > after_created,
                    and_(
                        Payment.created_at == after_created,
                        Payment.payment_id > after_id,
                    ),
                )
            )
        stmt = stmt.order_by(
            Payment.created_at.asc(),
            Payment.payment_id.asc(),
        ).limit(limit)
        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())

    async def get_payments_by_status(
        self, status: str, skip: int = 0, limit: int = 100
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

    async def count_payments_by_status(self, status: str) -> int:
        """指定 ``status`` 的支付总条数。"""
        stmt = select(func.count()).select_from(Payment).where(Payment.status == status)
        result = await self.db_session.execute(stmt)
        return int(result.scalar_one() or 0)
