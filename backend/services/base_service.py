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
        self,
        operation: Callable[[], Awaitable[Any]]
    ) -> Any:
        """在事务上下文中执行操作

        Args:
            operation: 异步操作函数，无参数

        Returns:
            操作结果

        Raises:
            重新抛出操作中的异常，事务会自动回滚
        """
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
