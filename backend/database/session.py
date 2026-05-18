#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
数据库会话管理
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from ..globals import settings
from .models import Base


# 创建异步引擎
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    poolclass=NullPool,  # 开发环境使用NullPool
)

# 创建异步会话工厂
async_session_maker = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# 保持向后兼容的函数
async def get_db_read() -> AsyncGenerator[AsyncSession, None]:
    """只读会话：结束隐式事务用 rollback，避免读路径 commit 的误导语义。"""
    async with async_session_maker() as session:
        try:
            yield session
            await session.rollback()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db_write() -> AsyncGenerator[AsyncSession, None]:
    """写入会话：单请求单事务；成功退出 `begin` 时提交，异常时回滚。"""
    async with async_session_maker() as session:
        async with session.begin():
            yield session


async def create_tables():
    """创建所有数据库表"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_tables():
    """删除所有数据库表"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
