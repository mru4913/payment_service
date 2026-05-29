#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
支付数据模型
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Dict, TYPE_CHECKING
from sqlalchemy import (
    String,
    Text,
    Numeric,
    BigInteger,
    ForeignKey,
    TIMESTAMP,
    Index,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .user import User


class Payment(Base):
    """支付记录表 - 美元基准金额存储"""

    __tablename__ = "payments"
    __table_args__ = (
        Index("idx_payment_telegram_id", "telegram_id"),
        Index("idx_payment_status", "status"),
        Index("idx_payment_method_status", "payment_method", "status"),
        Index("idx_payment_external_id", "external_payment_id"),
        Index(
            "uq_payment_method_external_id",
            "payment_method",
            "external_payment_id",
            unique=True,
            postgresql_where=text("external_payment_id IS NOT NULL"),
        ),
    )

    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, comment="支付ID"
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=False, comment="用户ID"
    )
    amount_usd: Mapped[Decimal] = mapped_column(
        Numeric(15, 6), nullable=False, comment="支付金额(美元)"
    )
    payment_method: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="支付方式"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", comment="支付状态"
    )
    external_payment_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="外部支付平台订单ID"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="支付描述"
    )
    payment_metadata: Mapped[Dict | None] = mapped_column(
        JSONB, nullable=True, comment="扩展元数据"
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), nullable=False, comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, nullable=True, comment="完成时间"
    )

    # 关联关系
    user: Mapped["User"] = relationship(back_populates="payments")
