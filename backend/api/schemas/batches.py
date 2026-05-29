#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Batch processing API schemas."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class BatchCreateResponse(BaseModel):
    batch_id: UUID
    batch_code: str
    status: str
    total_items: int
    estimated_hold_amount: Decimal
    created_at: datetime


class BatchStatusResponse(BaseModel):
    batch_id: UUID
    batch_code: str
    status: str
    task_type: str
    priority_type: str
    source_archive_name: str
    archive_format: str
    total_items: int
    succeeded_items: int
    failed_items: int
    estimated_hold_amount: Decimal
    result_archive_ready: bool = False
    created_at: datetime
    completed_at: datetime | None = None
    error_message: str | None = None


class BatchListItem(BaseModel):
    batch_id: UUID
    batch_code: str = Field(..., description="用户可见短批次编号")
    status: str
    task_type: str
    total_items: int
    succeeded_items: int
    failed_items: int
    created_at: datetime


class BatchListResponse(BaseModel):
    batches: list[BatchListItem]
    total: int
    returned: int
