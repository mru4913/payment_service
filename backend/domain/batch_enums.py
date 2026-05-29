#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Batch processing domain enums."""

from enum import StrEnum


class BatchStatus(StrEnum):
    """batch_jobs.status values."""

    VALIDATING = "validating"
    QUEUED = "queued"
    RUNNING = "running"
    PACKAGING = "packaging"
    DELIVERING = "delivering"
    COMPLETED = "completed"
    PARTIAL_FAILED = "partial_failed"
    FAILED = "failed"


class BatchItemStatus(StrEnum):
    """batch_items.status values."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
