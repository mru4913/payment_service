#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
余额交易数据模型
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from sqlalchemy import (
    String,
    Text,
    Numeric,
    BigInteger,
    ForeignKey,
    TIMESTAMP,
    Index,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .user import User
    from .payment import Payment


class BalanceTransaction(Base):
    """余额变动记录表 - 美元基准交易记录"""

    __tablename__ = "balance_transactions"
    __table_args__ = (
        Index("idx_bt_telegram_id", "telegram_id"),
        Index("idx_bt_payment_id", "payment_id"),
        Index("idx_bt_transaction_type", "transaction_type"),
    )

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, comment="交易ID"
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=False, comment="用户ID"
    )
    amount_usd: Mapped[Decimal] = mapped_column(
        Numeric(15, 6), nullable=False, comment="变动金额(美元)"
    )
    balance_before_usd: Mapped[Decimal] = mapped_column(
        Numeric(15, 6), nullable=False, comment="变动前余额(美元)"
    )
    balance_after_usd: Mapped[Decimal] = mapped_column(
        Numeric(15, 6), nullable=False, comment="变动后余额(美元)"
    )
    transaction_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="交易类型 (deposit, withdraw, payment, refund)",
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payments.payment_id"),
        nullable=True,
        comment="关联支付ID",
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="交易描述"
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), nullable=False, comment="创建时间"
    )

    # 关联关系
    user: Mapped["User"] = relationship(back_populates="balance_transactions")
    payment: Mapped["Payment"] = relationship()
