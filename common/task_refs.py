#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""User-facing task reference helpers."""

from __future__ import annotations

from uuid import UUID

_DEFAULT_CODE_LEN = 8


def public_task_code(task_id: UUID | str, length: int = _DEFAULT_CODE_LEN) -> str:
    """Return the short task code shown to users."""
    value = task_id.hex if isinstance(task_id, UUID) else str(task_id)
    clean = value.replace("-", "").strip()
    return clean[:length].upper()


def normalize_task_ref(raw: str) -> str:
    """Normalize a task ref accepted from Telegram input."""
    return raw.strip().replace("-", "").upper()
