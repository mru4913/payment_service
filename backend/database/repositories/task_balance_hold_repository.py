#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Task 余额冻结数据访问层 — 见 documents/04-BUSINESS-DESIGN.md §8.3
"""

import uuid
from typing import Any, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import TaskBalanceHold
from .base_repository import BaseRepository


class TaskBalanceHoldRepository(BaseRepository[TaskBalanceHold]):
    """冻结表仓库。`get` / `delete` 的 id 均为 **hold_id**。"""

    def __init__(self, db_session: AsyncSession):
        super().__init__(TaskBalanceHold, db_session)

    async def get(self, id: Any) -> Optional[TaskBalanceHold]:  # noqa: A002
        """按主键 hold_id 获取；非 UUID 时返回 None。"""
        if not isinstance(id, uuid.UUID):
            return None
        return await self.get_by_hold_id(id)

    async def delete(self, id: Any) -> bool:  # noqa: A002
        """按主键 hold_id 删除；非 UUID 时返回 False。"""
        if not isinstance(id, uuid.UUID):
            return False
        stmt = delete(TaskBalanceHold).where(TaskBalanceHold.hold_id == id)
        result = await self.db_session.execute(stmt)
        return result.rowcount > 0

    async def get_by_hold_id(self, hold_id: uuid.UUID) -> Optional[TaskBalanceHold]:
        """按 hold_id 获取。"""
        stmt = select(TaskBalanceHold).where(TaskBalanceHold.hold_id == hold_id)
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_task_id(self, task_id: uuid.UUID) -> Optional[TaskBalanceHold]:
        """按 task_id 获取冻结行（一对一）。"""
        stmt = select(TaskBalanceHold).where(TaskBalanceHold.task_id == task_id)
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_holds_by_telegram(
        self,
        telegram_id: int,
    ) -> List[TaskBalanceHold]:
        """用户当前 status=active 的冻结（风控、可用余额计算）。"""
        stmt = select(TaskBalanceHold).where(
            TaskBalanceHold.telegram_id == telegram_id,
            TaskBalanceHold.status == "active",
        )
        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())
