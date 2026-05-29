#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Batch processing HTTP API."""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query
from fastapi import UploadFile, status

from common.task_refs import public_task_code

from ...domain.task_enums import PriorityType
from ...globals import logger, settings
from ...services import BatchService, BatchServiceError
from ...services.batch_archives import (
    BatchArchiveError,
    ExtractedBatchArchive,
    cleanup_extracted_batch_archive,
    extract_batch_archive,
)
from ...services.task_pricing import TaskPricingError
from ...workers.compute_enqueue import enqueue_compute_task_with_record
from ..dependencies import batch_service_read, batch_service_write
from ..schemas.batches import (
    BatchCreateResponse,
    BatchListItem,
    BatchListResponse,
    BatchStatusResponse,
)

router = APIRouter(prefix="/batches", tags=["batches"])

_READ_CHUNK_BYTES = 1024 * 1024


def _batch_code(batch_id: UUID) -> str:
    return public_task_code(batch_id)


def _create_response(batch) -> BatchCreateResponse:
    return BatchCreateResponse(
        batch_id=batch.batch_id,
        batch_code=_batch_code(batch.batch_id),
        status=batch.status,
        total_items=batch.total_items,
        estimated_hold_amount=batch.estimated_hold_amount,
        created_at=batch.created_at,
    )


def _status_response(batch) -> BatchStatusResponse:
    return BatchStatusResponse(
        batch_id=batch.batch_id,
        batch_code=_batch_code(batch.batch_id),
        status=batch.status,
        task_type=batch.task_type,
        priority_type=batch.priority_type,
        source_archive_name=batch.source_archive_name,
        archive_format=batch.archive_format,
        total_items=batch.total_items,
        succeeded_items=batch.succeeded_items,
        failed_items=batch.failed_items,
        estimated_hold_amount=batch.estimated_hold_amount,
        result_archive_ready=bool(batch.result_archive_path),
        created_at=batch.created_at,
        completed_at=batch.completed_at,
        error_message=batch.error_message,
    )


def _list_item(batch) -> BatchListItem:
    return BatchListItem(
        batch_id=batch.batch_id,
        batch_code=_batch_code(batch.batch_id),
        status=batch.status,
        task_type=batch.task_type,
        total_items=batch.total_items,
        succeeded_items=batch.succeeded_items,
        failed_items=batch.failed_items,
        created_at=batch.created_at,
    )


def _service_error_to_http(exc: BatchServiceError) -> HTTPException:
    mapping: dict[str, int] = {
        "user_not_found": 404,
        "user_inactive": 403,
        "insufficient_funds": 402,
        "invalid_hold_amount": 422,
        "no_images": 422,
    }
    return HTTPException(
        status_code=mapping.get(exc.code, 400),
        detail={"message": exc.message, "code": exc.code},
    )


@router.post("/remove-watermark", response_model=BatchCreateResponse)
async def create_remove_watermark_batch(
    background_tasks: BackgroundTasks,
    telegram_id: int = Query(...),
    priority_type: PriorityType = Query(PriorityType.DEFAULT),
    archive: UploadFile = File(...),
    batch_service: BatchService = Depends(batch_service_write),
):
    """Create a remove-watermark batch from an uploaded ZIP/TAR archive."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await archive.read(_READ_CHUNK_BYTES):
        total += len(chunk)
        if total > settings.batch_archive_max_bytes:
            logger.warning(
                "batch_archive_rejected reason=file_too_large telegram_id=%s "
                "filename=%s bytes=%s max_bytes=%s",
                telegram_id,
                archive.filename,
                total,
                settings.batch_archive_max_bytes,
            )
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail={
                    "message": "压缩包超过大小限制",
                    "code": "archive_too_large",
                },
            )
        chunks.append(chunk)
    content = b"".join(chunks)

    extracted: ExtractedBatchArchive | None = None
    try:
        extracted = extract_batch_archive(
            content=content,
            filename=archive.filename or "archive",
            max_items=settings.batch_archive_max_items,
            max_unpacked_bytes=settings.batch_archive_max_unpacked_bytes,
            max_image_bytes=settings.upload_max_bytes,
        )
        result = await batch_service.create_remove_watermark_batch(
            telegram_id=telegram_id,
            priority_type=priority_type.value,
            archive=extracted,
        )
    except BatchArchiveError as e:
        removed = cleanup_extracted_batch_archive(extracted)
        logger.warning(
            "batch_archive_rejected telegram_id=%s filename=%s code=%s "
            "cleanup_removed=%s",
            telegram_id,
            archive.filename,
            e.code,
            removed,
        )
        raise HTTPException(
            status_code=422,
            detail={"message": e.message, "code": e.code},
        ) from e
    except TaskPricingError as e:
        removed = cleanup_extracted_batch_archive(extracted)
        logger.warning(
            "batch_create_failed telegram_id=%s priority=%s code=%s "
            "cleanup_removed=%s",
            telegram_id,
            priority_type.value,
            e.code,
            removed,
        )
        raise HTTPException(
            status_code=422,
            detail={"message": e.message, "code": e.code},
        ) from e
    except BatchServiceError as e:
        removed = cleanup_extracted_batch_archive(extracted)
        logger.warning(
            "batch_create_failed telegram_id=%s priority=%s code=%s "
            "cleanup_removed=%s",
            telegram_id,
            priority_type.value,
            e.code,
            removed,
        )
        raise _service_error_to_http(e) from e

    for task_id in result.task_ids:
        background_tasks.add_task(enqueue_compute_task_with_record, task_id)

    logger.info(
        "batch_create_result batch_id=%s telegram_id=%s items=%s priority=%s",
        result.batch.batch_id,
        telegram_id,
        result.batch.total_items,
        priority_type.value,
    )
    return _create_response(result.batch)


@router.get("/{batch_id}", response_model=BatchStatusResponse)
async def get_batch_status(
    batch_id: UUID,
    telegram_id: int = Query(...),
    batch_service: BatchService = Depends(batch_service_read),
):
    batch = await batch_service.get_batch_for_telegram(batch_id, telegram_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在或无权访问")
    return _status_response(batch)


@router.get("", response_model=BatchListResponse)
async def list_batches(
    telegram_id: int = Query(...),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=50),
    batch_service: BatchService = Depends(batch_service_read),
):
    batches, total = await batch_service.list_batches_for_telegram(
        telegram_id,
        skip=skip,
        limit=limit,
    )
    return BatchListResponse(
        batches=[_list_item(batch) for batch in batches],
        total=total,
        returned=len(batches),
    )
