#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
数据库会话管理
"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from ..globals import settings


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
async def get_db_read() -> AsyncSession:
    """读取操作会话 - 自动提交"""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()  # 读取操作直接提交
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db_write() -> AsyncSession:
    """写入操作会话 - 手动控制事务"""
    async with async_session_maker() as session:
        try:
            yield session
            # 不自动提交，由Service层控制事务
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_tables():
    """创建所有数据库表"""
    from .models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_tables():
    """删除所有数据库表"""
    from .models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
