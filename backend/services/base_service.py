#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
服务基类

事务边界由创建 `AsyncSession` 的入口统一承担，例如：
- FastAPI：`get_db_write()` 内 `async with session.begin(): yield session`
- Worker / 回调 / Bot：`async with async_session_maker() as session:` +
  `async with session.begin():`

Service 方法内不再调用 `session.begin()`，仅通过 repository 做 flush。
"""

from sqlalchemy.ext.asyncio import AsyncSession


class BaseService:
    """业务服务基类（会话由调用方注入，且调用方已保证事务边界）。"""

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session
