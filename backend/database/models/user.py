#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
用户数据模型
"""

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, TYPE_CHECKING
from sqlalchemy import String, Boolean, Numeric, BigInteger, TIMESTAMP, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .payment import Payment
    from .balance_transaction import BalanceTransaction
    from .task import Task
    from .task_balance_hold import TaskBalanceHold


class User(Base):
    """用户表 - Telegram详细信息 + 美元基准余额管理"""

    __tablename__ = "users"
    __table_args__ = (
        Index("idx_username", "telegram_username"),
        Index("idx_phone", "phone"),
        Index("idx_premium", "is_premium"),
        Index("idx_active", "is_active"),
    )

    # Telegram基本信息
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, comment="Telegram用户ID"
    )

    # Telegram账号状态
    is_premium: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否为Telegram Premium用户"
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否认证"
    )
    is_scam: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否标记为诈骗"
    )
    is_fake: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否标记为假账号"
    )

    # 系统字段
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="是否激活"
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

    # 财务信息 (美元基准)
    balance: Mapped[Decimal] = mapped_column(
        Numeric(15, 6),
        nullable=False,
        default=Decimal("0.000000"),
        comment="用户总余额(美元)；预授权冻结不减少本字段",
    )
    balance_held: Mapped[Decimal] = mapped_column(
        Numeric(15, 6),
        nullable=False,
        default=Decimal("0.000000"),
        comment=(
            "预授权冻结合计（与 balance 同币种）；冗余字段，"
            "应等于各 active hold 金额之和"
        ),
    )
    total_deposits: Mapped[Decimal] = mapped_column(
        Numeric(15, 6),
        nullable=False,
        default=Decimal("0.000000"),
        comment="累计充值(美元)",
    )
    total_withdrawals: Mapped[Decimal] = mapped_column(
        Numeric(15, 6),
        nullable=False,
        default=Decimal("0.000000"),
        comment="累计提现(美元)",
    )

    # 关联关系
    payments: Mapped[List["Payment"]] = relationship(back_populates="user")
    balance_transactions: Mapped[List["BalanceTransaction"]] = relationship(
        back_populates="user"
    )
    tasks: Mapped[List["Task"]] = relationship("Task", back_populates="user")
    task_balance_holds: Mapped[List["TaskBalanceHold"]] = relationship(
        "TaskBalanceHold",
        back_populates="user",
    )

    # 可选字段
    telegram_username: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Telegram用户名"
    )
    first_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="名"
    )
    last_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="姓"
    )
    phone: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="手机号"
    )
    preferences: Mapped[Dict | None] = mapped_column(
        JSONB, nullable=True, comment="用户偏好设置（JSON对象）"
    )

    @property
    def balance_available(self) -> Decimal:
        """可用余额（不持久化）= 总余额 - 冻结。"""
        return self.balance - self.balance_held

    @property
    def full_name(self) -> str:
        """获取完整姓名"""
        parts = [self.first_name, self.last_name]
        return " ".join(filter(None, parts)).strip()

    @property
    def display_name(self) -> str:
        """获取显示名称（优先使用用户名，其次是完整姓名）"""
        return self.telegram_username or self.full_name or f"User_{self.telegram_id}"
