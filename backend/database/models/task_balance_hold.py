#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Task 余额冻结
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Index, String, Numeric, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .user import User
    from .task import Task


class TaskBalanceHold(Base):
    """任务预授权冻结额度。"""

    __tablename__ = "task_balance_holds"
    __table_args__ = (Index("idx_tbh_telegram_id_status", "telegram_id", "status"),)

    hold_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, comment="冻结记录 ID"
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.task_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        comment="关联任务（一对一）；删除 Task 时级联删除本行",
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        nullable=False,
        comment="用户 Telegram ID",
    )
    amount_usd: Mapped[Decimal] = mapped_column(
        Numeric(15, 6), nullable=False, comment="冻结额度上限（美元）"
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="active / released / captured",
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), nullable=False, comment="创建时间"
    )
    released_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, nullable=True, comment="解冻或 capture 完成时间"
    )
    captured_amount_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 6), nullable=True, comment="实际划扣金额（美元）"
    )

    task: Mapped["Task"] = relationship("Task", back_populates="balance_hold")
    user: Mapped["User"] = relationship("User", back_populates="task_balance_holds")
