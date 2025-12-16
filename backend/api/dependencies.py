#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
API依赖注入配置
"""

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from ..database.session import get_db_read, get_db_write
from ..services import UserService, PaymentService, BalanceService


# 直接数据库会话依赖
async def db_read() -> AsyncGenerator[AsyncSession, None]:
    """读取数据库会话"""
    async for session in get_db_read():
        yield session


async def db_write() -> AsyncGenerator[AsyncSession, None]:
    """写入数据库会话"""
    async for session in get_db_write():
        yield session


# Service依赖 - 直接使用会话
def user_service_read(db: AsyncSession = Depends(db_read)) -> UserService:
    """用户服务 - 读取操作"""
    return UserService(db)


def user_service_write(db: AsyncSession = Depends(db_write)) -> UserService:
    """用户服务 - 写入操作"""
    return UserService(db)


def payment_service_read(db: AsyncSession = Depends(db_read)) -> PaymentService:
    """支付服务 - 读取操作"""
    return PaymentService(db)


def payment_service_write(db: AsyncSession = Depends(db_write)) -> PaymentService:
    """支付服务 - 写入操作"""
    return PaymentService(db)


def balance_service_read(db: AsyncSession = Depends(db_read)) -> BalanceService:
    """余额服务 - 读取操作"""
    return BalanceService(db)
