#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Worker 在任务写入终态后调用，释放或划扣 `balance_held`。"""

import asyncio
import uuid

from ..database.session import async_session_maker
from ..services.task_service import TaskService


async def settle_task_balance_hold_async(task_id: uuid.UUID) -> None:
    """异步结算预授权（终态任务）。"""
    async with async_session_maker() as session:
        async with session.begin():
            svc = TaskService(session)
            await svc.settle_balance_hold_for_terminal_task(task_id)


def settle_task_balance_hold(task_id: uuid.UUID) -> None:
    """同步入口（如 Celery 任务内）：`asyncio.run` 包装。"""
    asyncio.run(settle_task_balance_hold_async(task_id))
