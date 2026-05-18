#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
用户数据访问层
"""

from typing import Optional, List, Tuple

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from .base_repository import BaseRepository

_USER_WRITABLE_KEYS = frozenset(
    c.key for c in User.__table__.columns if c.key != "telegram_id"
)


class UserRepository(BaseRepository[User]):
    """用户数据仓库"""

    def __init__(self, db_session: AsyncSession):
        super().__init__(User, db_session)

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        """根据Telegram ID获取用户"""
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_telegram_id_for_update(self, telegram_id: int) -> Optional[User]:
        """按 Telegram ID 加载用户并加行锁（预授权 / 扣费 / 释放冻结）。"""
        stmt = select(User).where(User.telegram_id == telegram_id).with_for_update()
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
        """获取或创建用户。返回 (用户, 是否本次新建)。

        并发下使用 ``INSERT .. ON CONFLICT DO NOTHING``，避免双插主键导致
        ``IntegrityError`` 中断外层事务。
        """
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            return user, False

        filtered = {k: v for k, v in defaults.items() if k in _USER_WRITABLE_KEYS}
        stmt = (
            insert(User)
            .values(telegram_id=telegram_id, **filtered)
            .on_conflict_do_nothing(index_elements=["telegram_id"])
            .returning(User.telegram_id)
        )
        result = await self.db_session.execute(stmt)
        new_id = result.scalar_one_or_none()
        if new_id is not None:
            created_user = await self.get_by_telegram_id(telegram_id)
            if created_user is None:
                raise RuntimeError("get_or_create: inserted row not visible")
            return created_user, True

        existing = await self.get_by_telegram_id(telegram_id)
        if existing is None:
            raise RuntimeError("get_or_create: conflict but row missing")
        return existing, False
