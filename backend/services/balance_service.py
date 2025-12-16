#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
余额业务逻辑服务
"""

import uuid
from decimal import Decimal
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from .base_service import BaseService
from ..database.repositories import BalanceTransactionRepository
from ..database.models import BalanceTransaction


class BalanceService(BaseService):
    """余额业务服务"""

    def __init__(self, db_session: AsyncSession):
        super().__init__(db_session)
        self.balance_repo = BalanceTransactionRepository(db_session)

    async def get_user_transactions(
        self,
        telegram_id: int,
        skip: int = 0,
        limit: int = 20
    ) -> List[BalanceTransaction]:
        """获取用户余额交易记录"""
        return await self.balance_repo.get_user_transactions(telegram_id, skip, limit)

    async def get_transactions_by_type(
        self,
        transaction_type: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[BalanceTransaction]:
        """根据交易类型获取记录"""
        return await self.balance_repo.get_transactions_by_type(
            transaction_type, skip, limit
        )

    async def get_recent_transactions(
        self,
        days: int = 7,
        skip: int = 0,
        limit: int = 100
    ) -> List[BalanceTransaction]:
        """获取最近的交易记录"""
        return await self.balance_repo.get_recent_transactions(days, skip, limit)

    async def get_transaction_by_id(
        self,
        transaction_id: str
    ) -> Optional[BalanceTransaction]:
        """根据交易ID获取记录"""
        try:
            transaction_uuid = uuid.UUID(transaction_id)
        except ValueError:
            return None

        return await self.balance_repo.get_by_transaction_id(transaction_uuid)

    async def get_transaction_summary(
        self,
        telegram_id: int,
        days: int = 30
    ) -> Dict[str, Any]:
        """获取用户交易汇总"""
        transactions = await self.balance_repo.get_recent_transactions(days)

        # 筛选用户的交易
        user_transactions = [t for t in transactions if t.telegram_id == telegram_id]

        summary = {
            "total_transactions": len(user_transactions),
            "deposit_count": 0,
            "withdrawal_count": 0,
            "refund_count": 0,
            "total_deposit_amount": Decimal('0.0000'),
            "total_withdrawal_amount": Decimal('0.0000'),
            "total_refund_amount": Decimal('0.0000')
        }

        for transaction in user_transactions:
            if transaction.transaction_type == "deposit":
                summary["deposit_count"] += 1
                summary["total_deposit_amount"] += transaction.amount_usd
            elif transaction.transaction_type == "withdraw":
                summary["withdrawal_count"] += 1
                summary["total_withdrawal_amount"] += abs(transaction.amount_usd)
            elif transaction.transaction_type == "refund":
                summary["refund_count"] += 1
                summary["total_refund_amount"] += abs(transaction.amount_usd)

        return summary
