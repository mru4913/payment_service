#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Batch processing parent job."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List

from sqlalchemy import BigInteger, ForeignKey, Index, Numeric, String, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .batch_item import BatchItem
    from .user import User


class BatchJob(Base):
    """A user-visible batch container; child tasks do the actual compute work."""

    __tablename__ = "batch_jobs"
    __table_args__ = (
        Index("idx_batch_jobs_telegram_created", "telegram_id", "created_at"),
        Index("idx_batch_jobs_status_created", "status", "created_at"),
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=False
    )
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    priority_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_archive_name: Mapped[str] = mapped_column(String(255), nullable=False)
    archive_format: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    total_items: Mapped[int] = mapped_column(nullable=False, default=0)
    succeeded_items: Mapped[int] = mapped_column(nullable=False, default=0)
    failed_items: Mapped[int] = mapped_column(nullable=False, default=0)
    estimated_hold_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 6), nullable=False
    )
    result_archive_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    packaging_claim_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    packaging_claimed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)

    user: Mapped["User"] = relationship("User")
    items: Mapped[List["BatchItem"]] = relationship(
        "BatchItem",
        back_populates="batch",
        cascade="all, delete-orphan",
    )
