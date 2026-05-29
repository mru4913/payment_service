#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Batch processing repositories."""

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import case, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...domain.batch_enums import BatchItemStatus, BatchStatus
from ..models import BatchItem, BatchJob
from .base_repository import BaseRepository


class BatchJobRepository(BaseRepository[BatchJob]):
    """Repository for batch_jobs."""

    def __init__(self, db_session: AsyncSession):
        super().__init__(BatchJob, db_session)

    async def get(self, id: Any) -> Optional[BatchJob]:  # noqa: A002
        if not isinstance(id, uuid.UUID):
            return None
        return await self.get_by_batch_id(id)

    async def get_by_batch_id(
        self,
        batch_id: uuid.UUID,
        *,
        with_items: bool = False,
    ) -> Optional[BatchJob]:
        stmt = select(BatchJob).where(BatchJob.batch_id == batch_id)
        if with_items:
            stmt = stmt.options(selectinload(BatchJob.items))
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_telegram(
        self,
        batch_id: uuid.UUID,
        telegram_id: int,
    ) -> Optional[BatchJob]:
        stmt = select(BatchJob).where(
            BatchJob.batch_id == batch_id,
            BatchJob.telegram_id == telegram_id,
        )
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_telegram(
        self,
        telegram_id: int,
        *,
        skip: int = 0,
        limit: int = 20,
    ) -> list[BatchJob]:
        stmt = (
            select(BatchJob)
            .where(BatchJob.telegram_id == telegram_id)
            .order_by(desc(BatchJob.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())

    async def count_for_telegram(self, telegram_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(BatchJob)
            .where(BatchJob.telegram_id == telegram_id)
        )
        result = await self.db_session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def mark_running(self, batch_id: uuid.UUID) -> bool:
        stmt = (
            update(BatchJob)
            .where(
                BatchJob.batch_id == batch_id,
                BatchJob.status == BatchStatus.QUEUED.value,
            )
            .values(status=BatchStatus.RUNNING.value)
        )
        result = await self.db_session.execute(stmt)
        return (result.rowcount or 0) == 1

    async def mark_packaging(
        self,
        batch_id: uuid.UUID,
        *,
        succeeded_items: int,
        failed_items: int,
    ) -> bool:
        stmt = (
            update(BatchJob)
            .where(
                BatchJob.batch_id == batch_id,
                BatchJob.status.in_(
                    [
                        BatchStatus.QUEUED.value,
                        BatchStatus.RUNNING.value,
                    ]
                ),
            )
            .values(
                status=BatchStatus.PACKAGING.value,
                succeeded_items=succeeded_items,
                failed_items=failed_items,
            )
        )
        result = await self.db_session.execute(stmt)
        return (result.rowcount or 0) == 1

    async def claim_packaging_batch(
        self,
        batch_id: uuid.UUID,
        *,
        claim_id: str,
        claimed_at: datetime,
        stale_before: datetime,
    ) -> bool:
        """Atomically claim a packaging batch before sending archives."""
        stmt = (
            update(BatchJob)
            .where(
                BatchJob.batch_id == batch_id,
                BatchJob.status == BatchStatus.PACKAGING.value,
                or_(
                    BatchJob.packaging_claim_id.is_(None),
                    BatchJob.packaging_claimed_at.is_(None),
                    BatchJob.packaging_claimed_at <= stale_before,
                ),
            )
            .values(
                packaging_claim_id=claim_id,
                packaging_claimed_at=claimed_at,
            )
        )
        result = await self.db_session.execute(stmt)
        return (result.rowcount or 0) == 1

    async def refresh_packaging_claim(
        self,
        batch_id: uuid.UUID,
        *,
        claim_id: str,
        claimed_at: datetime,
    ) -> bool:
        """Refresh ownership before external side effects such as Telegram send."""
        stmt = (
            update(BatchJob)
            .where(
                BatchJob.batch_id == batch_id,
                BatchJob.status == BatchStatus.PACKAGING.value,
                BatchJob.packaging_claim_id == claim_id,
            )
            .values(packaging_claimed_at=claimed_at)
        )
        result = await self.db_session.execute(stmt)
        return (result.rowcount or 0) == 1

    async def complete_packaging_if_claimed(
        self,
        batch_id: uuid.UUID,
        *,
        claim_id: str,
        result_archive_path: str,
        completed_at: datetime,
    ) -> bool:
        """Finish packaging only for the current claim owner."""
        final_status = case(
            (
                BatchJob.failed_items == 0,
                BatchStatus.COMPLETED.value,
            ),
            else_=BatchStatus.PARTIAL_FAILED.value,
        )
        stmt = (
            update(BatchJob)
            .where(
                BatchJob.batch_id == batch_id,
                BatchJob.status == BatchStatus.PACKAGING.value,
                BatchJob.packaging_claim_id == claim_id,
            )
            .values(
                status=final_status,
                result_archive_path=result_archive_path,
                completed_at=completed_at,
                error_message=None,
                packaging_claim_id=None,
                packaging_claimed_at=None,
            )
        )
        result = await self.db_session.execute(stmt)
        return (result.rowcount or 0) == 1

    async def begin_delivery_if_claimed(
        self,
        batch_id: uuid.UUID,
        *,
        claim_id: str,
        result_archive_path: str,
        claimed_at: datetime,
    ) -> bool:
        """Persist result archive paths before Telegram side effects start."""
        stmt = (
            update(BatchJob)
            .where(
                BatchJob.batch_id == batch_id,
                BatchJob.status == BatchStatus.PACKAGING.value,
                BatchJob.packaging_claim_id == claim_id,
            )
            .values(
                status=BatchStatus.DELIVERING.value,
                result_archive_path=result_archive_path,
                packaging_claimed_at=claimed_at,
            )
        )
        result = await self.db_session.execute(stmt)
        return (result.rowcount or 0) == 1

    async def complete_delivery_if_claimed(
        self,
        batch_id: uuid.UUID,
        *,
        claim_id: str,
        completed_at: datetime,
    ) -> bool:
        """Finalize a delivery that has already crossed the external-send barrier."""
        final_status = case(
            (
                BatchJob.failed_items == 0,
                BatchStatus.COMPLETED.value,
            ),
            else_=BatchStatus.PARTIAL_FAILED.value,
        )
        stmt = (
            update(BatchJob)
            .where(
                BatchJob.batch_id == batch_id,
                BatchJob.status == BatchStatus.DELIVERING.value,
                BatchJob.packaging_claim_id == claim_id,
            )
            .values(
                status=final_status,
                completed_at=completed_at,
                error_message=None,
                packaging_claim_id=None,
                packaging_claimed_at=None,
            )
        )
        result = await self.db_session.execute(stmt)
        return (result.rowcount or 0) == 1

    async def mark_delivery_failed_if_claimed(
        self,
        batch_id: uuid.UUID,
        *,
        claim_id: str,
        completed_at: datetime,
        error_message: str,
    ) -> bool:
        """Fail a delivery attempt only if the current worker still owns it."""
        stmt = (
            update(BatchJob)
            .where(
                BatchJob.batch_id == batch_id,
                BatchJob.status == BatchStatus.DELIVERING.value,
                BatchJob.packaging_claim_id == claim_id,
            )
            .values(
                status=BatchStatus.FAILED.value,
                completed_at=completed_at,
                error_message=error_message[:500],
                packaging_claim_id=None,
                packaging_claimed_at=None,
            )
        )
        result = await self.db_session.execute(stmt)
        return (result.rowcount or 0) == 1

    async def mark_packaging_failed_if_claimed(
        self,
        batch_id: uuid.UUID,
        *,
        claim_id: str,
        completed_at: datetime,
        error_message: str,
    ) -> bool:
        """Fail packaging only for the current claim owner."""
        stmt = (
            update(BatchJob)
            .where(
                BatchJob.batch_id == batch_id,
                BatchJob.status == BatchStatus.PACKAGING.value,
                BatchJob.packaging_claim_id == claim_id,
            )
            .values(
                status=BatchStatus.FAILED.value,
                completed_at=completed_at,
                error_message=error_message[:500],
                packaging_claim_id=None,
                packaging_claimed_at=None,
            )
        )
        result = await self.db_session.execute(stmt)
        return (result.rowcount or 0) == 1


class BatchItemRepository(BaseRepository[BatchItem]):
    """Repository for batch_items."""

    def __init__(self, db_session: AsyncSession):
        super().__init__(BatchItem, db_session)

    async def get_by_task_id(self, task_id: uuid.UUID) -> Optional[BatchItem]:
        stmt = select(BatchItem).where(BatchItem.task_id == task_id)
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_running_by_task_id(self, task_id: uuid.UUID) -> bool:
        stmt = (
            update(BatchItem)
            .where(
                BatchItem.task_id == task_id,
                BatchItem.status == BatchItemStatus.QUEUED.value,
            )
            .values(status=BatchItemStatus.RUNNING.value)
        )
        result = await self.db_session.execute(stmt)
        return (result.rowcount or 0) == 1

    async def list_by_batch_id(self, batch_id: uuid.UUID) -> list[BatchItem]:
        stmt = (
            select(BatchItem)
            .where(BatchItem.batch_id == batch_id)
            .order_by(BatchItem.original_relative_path)
        )
        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())

    async def count_terminal_by_batch_id(self, batch_id: uuid.UUID) -> tuple[int, int]:
        stmt = (
            select(BatchItem.status, func.count())
            .where(BatchItem.batch_id == batch_id)
            .group_by(BatchItem.status)
        )
        result = await self.db_session.execute(stmt)
        counts = {str(status): int(count) for status, count in result.all()}
        return (
            counts.get(BatchItemStatus.SUCCEEDED.value, 0),
            counts.get(BatchItemStatus.FAILED.value, 0),
        )
