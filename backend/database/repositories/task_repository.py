#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
算力任务数据访问层
"""

import uuid
from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy import asc, delete, desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.task_enums import TaskStatus, ThirdPartyPlatform
from ..models import Task
from .base_repository import BaseRepository


class TaskRepository(BaseRepository[Task]):
    """Task 仓库。

    `get` / `delete` 的参数 id 表示 **task_id**（非 Base 默认的 model.id）。
    """

    def __init__(self, db_session: AsyncSession):
        super().__init__(Task, db_session)

    async def get(self, id: Any) -> Optional[Task]:  # noqa: A002 — 与 Base 签名一致
        """按主键 task_id 获取；非 UUID 时返回 None。"""
        if not isinstance(id, uuid.UUID):
            return None
        return await self.get_by_task_id(id)

    async def delete(self, id: Any) -> bool:  # noqa: A002
        """按主键 task_id 删除；非 UUID 时返回 False。"""
        if not isinstance(id, uuid.UUID):
            return False
        stmt = delete(Task).where(Task.task_id == id)
        result = await self.db_session.execute(stmt)
        return result.rowcount > 0

    async def get_by_task_id(self, task_id: uuid.UUID) -> Optional[Task]:
        """按 task_id 获取单条任务。"""
        stmt = select(Task).where(Task.task_id == task_id)
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(
        self, telegram_id: int, idempotency_key: str
    ) -> Optional[Task]:
        """同一用户 + 幂等键唯一（部分唯一索引）；用于重复提交检测。"""
        stmt = select(Task).where(
            Task.telegram_id == telegram_id,
            Task.idempotency_key == idempotency_key,
        )
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_platform_and_upstream_task_id(
        self,
        third_party_platform: str,
        upstream_task_id: str,
    ) -> Optional[Task]:
        """按平台 + 上游运行实例 ID 反查；多行时取一条，避免未唯一约束时抛异常。"""
        stmt = (
            select(Task)
            .where(
                Task.third_party_platform == third_party_platform,
                Task.upstream_task_id == upstream_task_id,
            )
            .limit(1)
        )
        result = await self.db_session.execute(stmt)
        return result.scalars().first()

    async def get_user_tasks(
        self,
        telegram_id: int,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Task]:
        """用户任务列表（按入队时间倒序）。"""
        stmt = (
            select(Task)
            .where(Task.telegram_id == telegram_id)
            .order_by(desc(Task.queued_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())

    async def get_tasks_by_status(
        self,
        status: str,
        skip: int = 0,
        limit: int = 100,
        queued_fifo: bool = False,
    ) -> List[Task]:
        """按状态分页。

        queued 且 queued_fifo 时按 queued_at 升序（调度 FIFO），否则按时间倒序。
        """
        stmt = select(Task).where(Task.status == status)
        if queued_fifo and status == "queued":
            stmt = stmt.order_by(asc(Task.queued_at))
        else:
            stmt = stmt.order_by(desc(Task.queued_at))
        stmt = stmt.offset(skip).limit(limit)
        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())

    async def list_pollable_running_tasks(
        self,
        limit: int = 30,
        *,
        platform: str = ThirdPartyPlatform.RUNNINGHUB.value,
    ) -> List[Task]:
        """RunningHub 等：``running`` 且已有 ``upstream_task_id``，供轮询终态。

        按 ``coalesce(started_at, queued_at)`` 升序，优先处理等待最久的行。
        """
        stmt = (
            select(Task)
            .where(
                Task.status == TaskStatus.RUNNING.value,
                Task.third_party_platform == platform,
                Task.upstream_task_id.isnot(None),
                Task.upstream_task_id != "",
            )
            .order_by(asc(func.coalesce(Task.started_at, Task.queued_at)))
            .limit(limit)
        )
        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())

    async def cas_transition_running_to_terminal(
        self,
        task_id: uuid.UUID,
        *,
        terminal_status: str,
        completed_at: datetime,
        result_payload: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        """仅当当前 ``status=running`` 时原子更新为终态；返回是否命中一行。"""
        vals: dict[str, Any] = {
            "status": terminal_status,
            "completed_at": completed_at,
        }
        if result_payload is not None:
            vals["result_payload"] = result_payload
        if terminal_status == TaskStatus.SUCCEEDED.value:
            vals["error_code"] = None
            vals["error_message"] = None
        else:
            if error_code is not None:
                vals["error_code"] = error_code
            if error_message is not None:
                vals["error_message"] = error_message
        stmt = (
            update(Task)
            .where(
                Task.task_id == task_id,
                Task.status == TaskStatus.RUNNING.value,
            )
            .values(**vals)
        )
        res = await self.db_session.execute(stmt)
        return (res.rowcount or 0) == 1

    async def get_user_tasks_by_type(
        self,
        telegram_id: int,
        task_type: str,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Task]:
        """按用户 + task_type 筛选（运营/统计）。"""
        stmt = (
            select(Task)
            .where(
                Task.telegram_id == telegram_id,
                Task.task_type == task_type,
            )
            .order_by(desc(Task.queued_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())
