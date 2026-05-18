#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
算力业务任务（Task）— 见 documents/04-BUSINESS-DESIGN.md §8.2
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    TIMESTAMP,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .balance_transaction import BalanceTransaction
    from .user import User
    from .task_balance_hold import TaskBalanceHold


class Task(Base):
    """业务任务表：第三方算力执行与计费单元。"""

    __tablename__ = "tasks"
    __table_args__ = (
        Index("idx_tasks_telegram_id_queued_at", "telegram_id", "queued_at"),
        Index("idx_tasks_status_queued_at", "status", "queued_at"),
        Index("idx_tasks_task_type_queued_at", "task_type", "queued_at"),
        Index(
            "idx_tasks_third_party_upstream",
            "third_party_platform",
            "upstream_task_id",
        ),
        Index(
            "uq_tasks_telegram_idempotency_key",
            "telegram_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, comment="任务ID"
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        nullable=False,
        comment="用户 Telegram ID",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="queued",
        comment="queued / running / succeeded / failed / cancelled",
    )
    task_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="业务任务类型（如 face_swap；与 workflow_recipes 键对齐）",
    )
    task_description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="展示用短说明"
    )
    third_party_platform: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="第三方平台编码，如 runninghub",
    )
    priority_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="算力档位，映射上游 instanceType，如 lite / default / plus",
    )
    input_payload: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="结构化入参（含 workflow_id 等，按 task_type 解释）",
    )
    result_payload: Mapped[Dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="结果摘要，如输出 URL 列表"
    )
    upstream_task_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="第三方本次运行实例 ID"
    )
    queued_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), nullable=False, comment="入队时间"
    )
    started_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, nullable=True, comment="开始执行时间"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, nullable=True, comment="终态时间"
    )
    billable_seconds: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 3), nullable=True, comment="可计费秒数"
    )
    charged_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 6), nullable=True, comment="实际扣费（美元）"
    )
    pricing_version: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="价目版本"
    )
    error_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="错误码"
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="错误信息"
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="幂等键"
    )
    celery_task_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="Celery 任务 ID"
    )

    user: Mapped["User"] = relationship("User", back_populates="tasks")
    balance_hold: Mapped["TaskBalanceHold | None"] = relationship(
        "TaskBalanceHold",
        back_populates="task",
        uselist=False,
    )
    balance_transactions: Mapped[List["BalanceTransaction"]] = relationship(
        "BalanceTransaction",
        back_populates="task",
    )
