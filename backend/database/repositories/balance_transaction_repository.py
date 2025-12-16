#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
余额交易数据访问层
"""

import uuid
from typing import Optional, List
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import BalanceTransaction
from .base_repository import BaseRepository


class BalanceTransactionRepository(BaseRepository[BalanceTransaction]):
    """余额交易数据仓库"""

    def __init__(self, db_session: AsyncSession):
        super().__init__(BalanceTransaction, db_session)

    async def get_by_transaction_id(
        self,
        transaction_id: uuid.UUID
    ) -> Optional[BalanceTransaction]:
        """根据交易ID获取记录"""
        stmt = select(BalanceTransaction).where(
            BalanceTransaction.transaction_id == transaction_id
        )
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_transactions(
        self,
        telegram_id: int,
        skip: int = 0,
        limit: int = 20
    ) -> List[BalanceTransaction]:
        """获取用户的余额交易记录"""
        stmt = (
            select(BalanceTransaction)
            .where(BalanceTransaction.telegram_id == telegram_id)
            .order_by(desc(BalanceTransaction.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())

    async def get_transactions_by_type(
        self,
        transaction_type: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[BalanceTransaction]:
        """根据交易类型获取记录"""
        stmt = (
            select(BalanceTransaction)
            .where(BalanceTransaction.transaction_type == transaction_type)
            .order_by(desc(BalanceTransaction.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())

    async def get_recent_transactions(
        self,
        days: int = 7,
        skip: int = 0,
        limit: int = 100
    ) -> List[BalanceTransaction]:
        """获取最近的交易记录"""
        from datetime import datetime, timedelta, timezone
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

        stmt = (
            select(BalanceTransaction)
            .where(BalanceTransaction.created_at >= cutoff_date)
            .order_by(desc(BalanceTransaction.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())
