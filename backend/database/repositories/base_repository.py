#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
基础数据仓库抽象类
所有数据仓库都应继承自此基类
"""

from abc import ABC
from typing import Generic, TypeVar, Type, List, Optional, Dict, Any
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

# 定义一个类型变量，用于表示ORM模型
ModelType = TypeVar("ModelType", bound=DeclarativeBase)


class BaseRepository(ABC, Generic[ModelType]):
    """
    抽象基类，用于定义所有数据仓库的通用接口。
    实现了基本的CRUD操作。
    """

    def __init__(self, model: Type[ModelType], db_session: AsyncSession):
        self.model = model
        self.db_session = db_session

    async def create(self, obj_in: ModelType) -> ModelType:
        """创建新的记录 - 只添加和刷新，不提交"""
        self.db_session.add(obj_in)
        await self.db_session.flush()  # 刷新到数据库，但不提交
        await self.db_session.refresh(obj_in)
        return obj_in

    async def get(self, id: Any) -> Optional[ModelType]:
        """根据ID获取记录"""
        stmt = select(self.model).where(self.model.id == id)  # 假设模型有id字段
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_multi(self, skip: int = 0, limit: int = 100) -> List[ModelType]:
        """获取多条记录"""
        stmt = select(self.model).offset(skip).limit(limit)
        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, db_obj: ModelType, obj_in: Dict[str, Any]) -> ModelType:
        """更新记录 - 只修改和刷新，不提交"""
        for field, value in obj_in.items():
            setattr(db_obj, field, value)
        await self.db_session.flush()
        await self.db_session.refresh(db_obj)
        return db_obj

    async def delete(self, id: Any) -> bool:
        """删除记录 - 只执行删除，不提交"""
        stmt = delete(self.model).where(self.model.id == id)
        result = await self.db_session.execute(stmt)
        return result.rowcount > 0

    # 显式事务控制方法（可选使用）
    async def commit(self):
        """显式提交当前会话"""
        await self.db_session.commit()

    async def rollback(self):
        """回滚当前会话"""
        await self.db_session.rollback()

    async def begin_transaction(self):
        """开始显式事务"""
        return await self.db_session.begin()
