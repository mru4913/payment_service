#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
用户业务逻辑服务
"""

import uuid
from typing import Optional, Dict, Any, Tuple
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession

from .base_service import BaseService
from ..database.repositories import UserRepository, BalanceTransactionRepository
from ..database.models import User, BalanceTransaction


class BalanceBelowHeldError(Exception):
    """扣减后总余额将低于已冻结金额（balance < balance_held）。"""

    def __init__(self, message: str = "扣减后总余额不能低于已冻结金额") -> None:
        self.message = message
        self.code = "balance_below_held"
        super().__init__(message)


class UserService(BaseService):
    """用户业务服务"""

    def __init__(self, db_session: AsyncSession):
        super().__init__(db_session)
        self.user_repo = UserRepository(db_session)
        self.balance_repo = BalanceTransactionRepository(db_session)

    async def get_user(self, telegram_id: int) -> Optional[User]:
        """根据Telegram ID获取用户"""
        return await self.user_repo.get_by_telegram_id(telegram_id)

    async def get_user_by_username(self, username: str) -> Optional[User]:
        """根据用户名获取用户"""
        return await self.user_repo.get_by_username(username)

    async def update_user(self, telegram_id: int, **update_data) -> Optional[User]:
        """更新用户信息"""
        user = await self.user_repo.get_by_telegram_id(telegram_id)
        if not user:
            return None
        return await self.user_repo.update(user, update_data)

    async def get_or_create_user(
        self, telegram_id: int, **defaults
    ) -> Tuple[User, bool]:
        """获取或创建用户，返回 (用户, 是否本次新建)。"""
        return await self.user_repo.get_or_create(telegram_id, **defaults)

    async def update_balance(
        self,
        telegram_id: int,
        amount: Decimal,
        transaction_type: str,
        payment_id: Optional[uuid.UUID] = None,
        description: str = "",
    ) -> Optional[User]:
        """更新用户余额并记录交易（与调用方同一事务）。"""
        user = await self.user_repo.get_by_telegram_id_for_update(telegram_id)
        if not user:
            return None

        old_balance = user.balance
        new_balance = old_balance + amount

        if new_balance < user.balance_held:
            raise BalanceBelowHeldError()

        user.balance = new_balance
        if amount > 0:
            user.total_deposits += amount
        else:
            user.total_withdrawals += abs(amount)

        transaction = BalanceTransaction(
            telegram_id=telegram_id,
            amount_usd=amount,
            balance_before_usd=old_balance,
            balance_after_usd=new_balance,
            transaction_type=transaction_type,
            payment_id=payment_id,
            description=description,
        )

        await self.user_repo.update(
            user,
            {
                "balance": new_balance,
                "total_deposits": user.total_deposits,
                "total_withdrawals": user.total_withdrawals,
            },
        )
        await self.balance_repo.create(transaction)

        return user

    async def get_user_balance(self, telegram_id: int) -> Optional[Decimal]:
        """获取用户余额"""
        user = await self.user_repo.get_by_telegram_id(telegram_id)
        return user.balance if user else None

    async def get_user_stats(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """获取用户统计信息"""
        user = await self.user_repo.get_by_telegram_id(telegram_id)
        if not user:
            return None

        return {
            "telegram_id": user.telegram_id,
            "balance": user.balance,
            "balance_held": user.balance_held,
            "balance_available": user.balance_available,
            "total_deposits": user.total_deposits,
            "total_withdrawals": user.total_withdrawals,
            "is_premium": user.is_premium,
            "is_verified": user.is_verified,
            "created_at": user.created_at,
            "display_name": user.display_name,
        }

    async def deactivate_user(self, telegram_id: int) -> bool:
        """停用用户账户"""
        user = await self.user_repo.get_by_telegram_id(telegram_id)
        if not user:
            return False
        await self.user_repo.update(user, {"is_active": False})
        return True

    async def activate_user(self, telegram_id: int) -> bool:
        """激活用户账户"""
        user = await self.user_repo.get_by_telegram_id(telegram_id)
        if not user:
            return False
        await self.user_repo.update(user, {"is_active": True})
        return True
