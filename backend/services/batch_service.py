#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Batch orchestration service for archive-based workflows."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from common.task_results import extract_result_image_urls

from .base_service import BaseService
from .batch_archives import (
    ExtractedBatchArchive,
    result_relative_path,
)
from .task_pricing import estimate_task_hold
from ..database.models import (
    BalanceTransaction,
    BatchItem,
    BatchJob,
    Task,
    TaskBalanceHold,
)
from ..database.repositories import (
    BalanceTransactionRepository,
    BatchItemRepository,
    BatchJobRepository,
    TaskBalanceHoldRepository,
    TaskRepository,
    UserRepository,
)
from ..domain.balance_transaction_types import BalanceTransactionType
from ..domain.batch_enums import BatchItemStatus, BatchStatus
from ..domain.task_enums import TaskBalanceHoldStatus, TaskStatus
from ..domain.task_prompts import REMOVE_WATERMARK_PROMPT


class BatchServiceError(Exception):
    """Batch domain error."""

    def __init__(self, message: str, code: str = "batch_error") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class BatchCreateResult:
    """Created batch and child task IDs to enqueue after commit."""

    batch: BatchJob
    task_ids: list[uuid.UUID]


@dataclass(frozen=True, slots=True)
class BatchTerminalAction:
    """What worker code should do after recording a child terminal state."""

    is_batch_task: bool
    batch_id: uuid.UUID | None = None
    should_package: bool = False
    should_notify_failed: bool = False


class BatchService(BaseService):
    """Create and summarize batch jobs while keeping task execution unchanged."""

    def __init__(self, db_session) -> None:
        super().__init__(db_session)
        self.user_repo = UserRepository(db_session)
        self.task_repo = TaskRepository(db_session)
        self.hold_repo = TaskBalanceHoldRepository(db_session)
        self.balance_repo = BalanceTransactionRepository(db_session)
        self.batch_repo = BatchJobRepository(db_session)
        self.item_repo = BatchItemRepository(db_session)

    async def create_remove_watermark_batch(
        self,
        *,
        telegram_id: int,
        priority_type: str,
        archive: ExtractedBatchArchive,
    ) -> BatchCreateResult:
        """Create one batch job plus one normal remove_watermark task per image."""
        if not archive.images:
            raise BatchServiceError("压缩包内没有可处理图片", "no_images")

        hold_per_item = estimate_task_hold("remove_watermark", priority_type)
        total_hold = hold_per_item * Decimal(len(archive.images))
        if total_hold <= 0:
            raise BatchServiceError("预授权金额无效", "invalid_hold_amount")

        user = await self.user_repo.get_by_telegram_id_for_update(telegram_id)
        if not user:
            raise BatchServiceError("用户不存在", "user_not_found")
        if not user.is_active:
            raise BatchServiceError("用户未激活", "user_inactive")
        available = user.balance - user.balance_held
        if available < total_hold:
            raise BatchServiceError("可用余额不足", "insufficient_funds")

        batch = BatchJob(
            batch_id=uuid.uuid4(),
            telegram_id=telegram_id,
            task_type="remove_watermark",
            priority_type=priority_type,
            source_archive_name=archive.source_archive_name,
            archive_format=archive.archive_format,
            status=BatchStatus.QUEUED.value,
            total_items=len(archive.images),
            succeeded_items=0,
            failed_items=0,
            estimated_hold_amount=total_hold,
        )
        await self.batch_repo.create(batch)

        task_ids: list[uuid.UUID] = []
        for image in archive.images:
            task_id = uuid.uuid4()
            task = Task(
                task_id=task_id,
                telegram_id=telegram_id,
                status=TaskStatus.QUEUED.value,
                task_type="remove_watermark",
                task_description=f"batch:{batch.batch_id}",
                third_party_platform="runninghub",
                priority_type=priority_type,
                input_payload={
                    "image": image.file_ref,
                    "prompt": REMOVE_WATERMARK_PROMPT,
                },
            )
            await self.task_repo.create(task)

            hold = TaskBalanceHold(
                hold_id=uuid.uuid4(),
                task_id=task_id,
                telegram_id=telegram_id,
                amount_usd=hold_per_item,
                status=TaskBalanceHoldStatus.ACTIVE.value,
            )
            await self.hold_repo.create(hold)

            item = BatchItem(
                item_id=uuid.uuid4(),
                batch_id=batch.batch_id,
                task_id=task_id,
                original_relative_path=image.relative_path,
                result_relative_path=None,
                input_file_ref=image.file_ref,
                result_url=None,
                status=BatchItemStatus.QUEUED.value,
            )
            await self.item_repo.create(item)

            tx = BalanceTransaction(
                telegram_id=telegram_id,
                amount_usd=hold_per_item,
                balance_before_usd=user.balance,
                balance_after_usd=user.balance,
                transaction_type=BalanceTransactionType.HOLD,
                task_id=task_id,
                description=f"batch pre-authorization hold {batch.batch_id}",
            )
            await self.balance_repo.create(tx)
            task_ids.append(task_id)

        await self.user_repo.update(
            user,
            {"balance_held": user.balance_held + total_hold},
        )
        return BatchCreateResult(batch=batch, task_ids=task_ids)

    async def get_batch_for_telegram(
        self,
        batch_id: uuid.UUID,
        telegram_id: int,
    ) -> BatchJob | None:
        return await self.batch_repo.get_for_telegram(batch_id, telegram_id)

    async def list_batches_for_telegram(
        self,
        telegram_id: int,
        *,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[BatchJob], int]:
        batches = await self.batch_repo.list_for_telegram(
            telegram_id,
            skip=skip,
            limit=limit,
        )
        total = await self.batch_repo.count_for_telegram(telegram_id)
        return batches, total

    async def list_items(self, batch_id: uuid.UUID) -> list[BatchItem]:
        return await self.item_repo.list_by_batch_id(batch_id)

    async def is_batch_task(self, task_id: uuid.UUID) -> bool:
        """Return whether a compute task belongs to a batch."""
        return await self.item_repo.get_by_task_id(task_id) is not None

    async def mark_task_running(self, task_id: uuid.UUID) -> bool:
        """Mark a child item and parent batch as running when RH starts."""
        item = await self.item_repo.get_by_task_id(task_id)
        if not item:
            return False
        await self.item_repo.mark_running_by_task_id(task_id)
        await self.batch_repo.mark_running(item.batch_id)
        return True

    async def record_task_terminal(
        self,
        *,
        task_id: uuid.UUID,
        terminal_status: str,
        result_payload: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> BatchTerminalAction:
        """Update batch item state after a child task reaches terminal status."""
        item = await self.item_repo.get_by_task_id(task_id)
        if not item:
            return BatchTerminalAction(is_batch_task=False)

        batch = await self.batch_repo.get_by_batch_id(item.batch_id)
        if not batch:
            return BatchTerminalAction(is_batch_task=True, batch_id=item.batch_id)

        if batch.status in {
            BatchStatus.COMPLETED.value,
            BatchStatus.PARTIAL_FAILED.value,
            BatchStatus.FAILED.value,
        }:
            return BatchTerminalAction(is_batch_task=True, batch_id=batch.batch_id)

        if item.status not in {
            BatchItemStatus.SUCCEEDED.value,
            BatchItemStatus.FAILED.value,
        }:
            updates: dict[str, Any]
            if terminal_status == TaskStatus.SUCCEEDED.value:
                urls = extract_result_image_urls(result_payload)
                result_url = urls[0] if urls else None
                if result_url:
                    updates = {
                        "status": BatchItemStatus.SUCCEEDED.value,
                        "result_url": result_url,
                        "result_relative_path": result_relative_path(
                            item.original_relative_path
                        ),
                        "error_message": None,
                    }
                else:
                    updates = {
                        "status": BatchItemStatus.FAILED.value,
                        "error_message": "任务成功但未返回结果图片",
                    }
            else:
                updates = {
                    "status": BatchItemStatus.FAILED.value,
                    "error_message": (error_message or "任务处理失败")[:500],
                }
            await self.item_repo.update(item, updates)

        succeeded, failed = await self.item_repo.count_terminal_by_batch_id(
            batch.batch_id
        )
        terminal_count = succeeded + failed
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if terminal_count < batch.total_items:
            if batch.status not in {
                BatchStatus.PACKAGING.value,
                BatchStatus.COMPLETED.value,
                BatchStatus.PARTIAL_FAILED.value,
                BatchStatus.FAILED.value,
            }:
                await self.batch_repo.update(
                    batch,
                    {
                        "status": BatchStatus.RUNNING.value,
                        "succeeded_items": succeeded,
                        "failed_items": failed,
                    },
                )
            return BatchTerminalAction(
                is_batch_task=True,
                batch_id=batch.batch_id,
            )

        if batch.status == BatchStatus.PACKAGING.value:
            return BatchTerminalAction(is_batch_task=True, batch_id=batch.batch_id)

        if succeeded == 0:
            await self.batch_repo.update(
                batch,
                {
                    "status": BatchStatus.FAILED.value,
                    "succeeded_items": succeeded,
                    "failed_items": failed,
                    "completed_at": now,
                    "error_message": "批量任务全部失败",
                },
            )
            return BatchTerminalAction(
                is_batch_task=True,
                batch_id=batch.batch_id,
                should_notify_failed=True,
            )

        should_package = await self.batch_repo.mark_packaging(
            batch.batch_id,
            succeeded_items=succeeded,
            failed_items=failed,
        )
        return BatchTerminalAction(
            is_batch_task=True,
            batch_id=batch.batch_id,
            should_package=should_package,
        )

    async def complete_packaging(
        self,
        *,
        batch_id: uuid.UUID,
        claim_id: str,
        result_archive_path: str,
    ) -> bool:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return await self.batch_repo.complete_packaging_if_claimed(
            batch_id,
            claim_id=claim_id,
            result_archive_path=result_archive_path,
            completed_at=now,
        )

    async def begin_delivery(
        self,
        *,
        batch_id: uuid.UUID,
        claim_id: str,
        result_archive_path: str,
    ) -> bool:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return await self.batch_repo.begin_delivery_if_claimed(
            batch_id,
            claim_id=claim_id,
            result_archive_path=result_archive_path,
            claimed_at=now,
        )

    async def complete_delivery(
        self,
        *,
        batch_id: uuid.UUID,
        claim_id: str,
    ) -> bool:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return await self.batch_repo.complete_delivery_if_claimed(
            batch_id,
            claim_id=claim_id,
            completed_at=now,
        )

    async def claim_packaging_batch(
        self,
        *,
        batch_id: uuid.UUID,
        claim_id: str,
        stale_before: datetime,
    ) -> bool:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return await self.batch_repo.claim_packaging_batch(
            batch_id,
            claim_id=claim_id,
            claimed_at=now,
            stale_before=stale_before,
        )

    async def refresh_packaging_claim(
        self,
        *,
        batch_id: uuid.UUID,
        claim_id: str,
    ) -> bool:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return await self.batch_repo.refresh_packaging_claim(
            batch_id,
            claim_id=claim_id,
            claimed_at=now,
        )

    async def mark_packaging_failed(
        self,
        *,
        batch_id: uuid.UUID,
        claim_id: str,
        error_message: str,
    ) -> bool:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return await self.batch_repo.mark_packaging_failed_if_claimed(
            batch_id,
            claim_id=claim_id,
            completed_at=now,
            error_message=error_message,
        )

    async def mark_delivery_failed(
        self,
        *,
        batch_id: uuid.UUID,
        claim_id: str,
        error_message: str,
    ) -> bool:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return await self.batch_repo.mark_delivery_failed_if_claimed(
            batch_id,
            claim_id=claim_id,
            completed_at=now,
            error_message=error_message,
        )
