#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
用户数据访问层
"""

from typing import Optional, List, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from .base_repository import BaseRepository


class UserRepository(BaseRepository[User]):
    """用户数据仓库"""

    def __init__(self, db_session: AsyncSession):
        super().__init__(User, db_session)

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        """根据Telegram ID获取用户"""
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> Optional[User]:
        """根据用户名获取用户"""
        stmt = select(User).where(User.telegram_username == username)
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_users(self, skip: int = 0, limit: int = 100) -> List[User]:
        """获取活跃用户"""
        stmt = select(User).where(User.is_active).offset(skip).limit(limit)
        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())

    async def get_premium_users(self, skip: int = 0, limit: int = 100) -> List[User]:
        """获取Premium用户"""
        stmt = select(User).where(User.is_premium).offset(skip).limit(limit)
        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())

    async def get_or_create(self, telegram_id: int, **defaults) -> Tuple[User, bool]:
        """获取或创建用户。返回 (用户, 是否本次新建)。"""
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            return user, False

        user_data = {"telegram_id": telegram_id, **defaults}
        user = User(**user_data)
        created = await self.create(user)
        return created, True
