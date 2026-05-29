#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Batch item mapped to one compute task."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .batch_job import BatchJob
    from .task import Task


class BatchItem(Base):
    """One archive image and its corresponding task/result state."""

    __tablename__ = "batch_items"
    __table_args__ = (
        Index("idx_batch_items_batch_id", "batch_id"),
        Index("idx_batch_items_task_id", "task_id", unique=True),
    )

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("batch_jobs.batch_id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.task_id", ondelete="CASCADE"),
        nullable=False,
    )
    original_relative_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    result_relative_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )
    input_file_ref: Mapped[str] = mapped_column(Text, nullable=False)
    result_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    batch: Mapped["BatchJob"] = relationship("BatchJob", back_populates="items")
    task: Mapped["Task"] = relationship("Task")
