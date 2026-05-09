#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
服务基类 - 提供事务控制功能
"""

from typing import Any, Callable, Awaitable
from sqlalchemy.ext.asyncio import AsyncSession


class BaseService:
    """服务基类 - 提供统一的事务控制"""

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session

    async def execute_in_transaction(
        self, operation: Callable[[], Awaitable[Any]]
    ) -> Any:
        """在事务上下文中执行操作

        若当前会话已在事务中（例如 PaymentService 嵌套调用 UserService），
        则不再调用 begin()，避免 SQLAlchemy 抛出「事务已开启」错误。
        """
        if self.db_session.in_transaction():
            return await operation()
        async with self.db_session.begin():
            return await operation()

    async def execute_readonly(self, operation: Callable[[], Awaitable[Any]]) -> Any:
        """执行只读操作（不开启事务）

        Args:
            operation: 异步操作函数，无参数

        Returns:
            操作结果
        """
        return await operation()

    async def commit_changes(self):
        """显式提交当前会话的变更"""
        await self.db_session.commit()

    async def rollback_changes(self):
        """回滚当前会话的变更"""
        await self.db_session.rollback()
