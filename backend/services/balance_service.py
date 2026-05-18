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
from ..domain.balance_transaction_types import BalanceTransactionType
from ..database.repositories import BalanceTransactionRepository
from ..database.models import BalanceTransaction


class BalanceService(BaseService):
    """余额业务服务"""

    def __init__(self, db_session: AsyncSession):
        super().__init__(db_session)
        self.balance_repo = BalanceTransactionRepository(db_session)

    async def get_user_transactions(
        self, telegram_id: int, skip: int = 0, limit: int = 20
    ) -> List[BalanceTransaction]:
        """获取用户余额交易记录"""
        return await self.balance_repo.get_user_transactions(telegram_id, skip, limit)

    async def count_user_transactions(self, telegram_id: int) -> int:
        """用户余额流水总条数。"""
        return await self.balance_repo.count_user_transactions(telegram_id)

    async def get_transactions_by_type(
        self, transaction_type: str, skip: int = 0, limit: int = 100
    ) -> List[BalanceTransaction]:
        """根据交易类型获取记录"""
        return await self.balance_repo.get_transactions_by_type(
            transaction_type, skip, limit
        )

    async def count_transactions_by_type(self, transaction_type: str) -> int:
        return await self.balance_repo.count_transactions_by_type(transaction_type)

    async def get_recent_transactions(
        self, days: int = 7, skip: int = 0, limit: int = 100
    ) -> List[BalanceTransaction]:
        """获取最近的交易记录"""
        return await self.balance_repo.get_recent_transactions(days, skip, limit)

    async def count_recent_transactions(self, days: int = 7) -> int:
        return await self.balance_repo.count_recent_transactions(days)

    async def get_transaction_by_id(
        self, transaction_id: str
    ) -> Optional[BalanceTransaction]:
        """根据交易ID获取记录"""
        try:
            transaction_uuid = uuid.UUID(transaction_id)
        except ValueError:
            return None

        return await self.balance_repo.get_by_transaction_id(transaction_uuid)

    async def get_transaction_summary(
        self, telegram_id: int, days: int = 30
    ) -> Dict[str, Any]:
        """获取用户交易汇总（按用户 + 时间窗口查询，避免全局 limit 截断导致统计偏小）"""
        user_transactions = await self.balance_repo.get_user_transactions_in_period(
            telegram_id, days
        )

        summary = {
            "total_transactions": len(user_transactions),
            "deposit_count": 0,
            "withdrawal_count": 0,
            "refund_count": 0,
            "payment_count": 0,
            "hold_count": 0,
            "hold_release_count": 0,
            "consumption_count": 0,
            "total_deposit_amount": Decimal("0"),
            "total_withdrawal_amount": Decimal("0"),
            "total_refund_amount": Decimal("0"),
            "total_payment_amount": Decimal("0"),
            "total_hold_amount": Decimal("0"),
            "total_hold_release_amount": Decimal("0"),
            "total_consumption_amount": Decimal("0"),
        }

        for transaction in user_transactions:
            t = transaction.transaction_type
            amt = transaction.amount_usd
            if t == BalanceTransactionType.DEPOSIT:
                summary["deposit_count"] += 1
                summary["total_deposit_amount"] += amt
            elif t == BalanceTransactionType.WITHDRAW:
                summary["withdrawal_count"] += 1
                summary["total_withdrawal_amount"] += abs(amt)
            elif t == BalanceTransactionType.REFUND:
                summary["refund_count"] += 1
                summary["total_refund_amount"] += abs(amt)
            elif t == BalanceTransactionType.PAYMENT:
                summary["payment_count"] += 1
                summary["total_payment_amount"] += abs(amt)
            elif t == BalanceTransactionType.HOLD:
                summary["hold_count"] += 1
                summary["total_hold_amount"] += abs(amt)
            elif t == BalanceTransactionType.HOLD_RELEASE:
                summary["hold_release_count"] += 1
                summary["total_hold_release_amount"] += abs(amt)
            elif t == BalanceTransactionType.CONSUMPTION:
                summary["consumption_count"] += 1
                summary["total_consumption_amount"] += abs(amt)

        return summary
