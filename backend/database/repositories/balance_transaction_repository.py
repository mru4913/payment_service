#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
余额交易数据访问层
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import BalanceTransaction
from .base_repository import BaseRepository


class BalanceTransactionRepository(BaseRepository[BalanceTransaction]):
    """余额交易数据仓库"""

    def __init__(self, db_session: AsyncSession):
        super().__init__(BalanceTransaction, db_session)

    async def get_by_transaction_id(
        self, transaction_id: uuid.UUID
    ) -> Optional[BalanceTransaction]:
        """根据交易ID获取记录"""
        stmt = select(BalanceTransaction).where(
            BalanceTransaction.transaction_id == transaction_id
        )
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_transactions(
        self, telegram_id: int, skip: int = 0, limit: int = 20
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

    async def count_user_transactions(self, telegram_id: int) -> int:
        """用户余额流水总条数（分页 total 用）。"""
        stmt = (
            select(func.count())
            .select_from(BalanceTransaction)
            .where(BalanceTransaction.telegram_id == telegram_id)
        )
        result = await self.db_session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def get_user_transactions_in_period(
        self,
        telegram_id: int,
        days: int,
        limit: int = 5000,
    ) -> List[BalanceTransaction]:
        """某用户在最近 days 天内的交易（按时间倒序，用于汇总统计）。"""
        # 列为 naive UTC；用 naive 比较，避免 asyncpg tz-aware/naive 混用
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).replace(
            tzinfo=None
        )
        stmt = (
            select(BalanceTransaction)
            .where(
                BalanceTransaction.telegram_id == telegram_id,
                BalanceTransaction.created_at >= cutoff_date,
            )
            .order_by(desc(BalanceTransaction.created_at))
            .limit(limit)
        )
        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())

    async def get_transactions_by_type(
        self, transaction_type: str, skip: int = 0, limit: int = 100
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

    async def count_transactions_by_type(self, transaction_type: str) -> int:
        """指定 ``transaction_type`` 的流水总条数。"""
        stmt = (
            select(func.count())
            .select_from(BalanceTransaction)
            .where(BalanceTransaction.transaction_type == transaction_type)
        )
        result = await self.db_session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def get_recent_transactions(
        self, days: int = 7, skip: int = 0, limit: int = 100
    ) -> List[BalanceTransaction]:
        """获取最近的交易记录"""
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).replace(
            tzinfo=None
        )

        stmt = (
            select(BalanceTransaction)
            .where(BalanceTransaction.created_at >= cutoff_date)
            .order_by(desc(BalanceTransaction.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())

    async def count_recent_transactions(self, days: int = 7) -> int:
        """最近 ``days`` 天内流水总条数；时间窗同 ``get_recent_transactions``。"""
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).replace(
            tzinfo=None
        )
        stmt = (
            select(func.count())
            .select_from(BalanceTransaction)
            .where(BalanceTransaction.created_at >= cutoff_date)
        )
        result = await self.db_session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def get_transactions_by_task_id(
        self,
        task_id: uuid.UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> List[BalanceTransaction]:
        """某算力任务关联的余额流水（消费 / 冻结 / 解冻等）。"""
        stmt = (
            select(BalanceTransaction)
            .where(BalanceTransaction.task_id == task_id)
            .order_by(desc(BalanceTransaction.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())
