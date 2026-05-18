# -*- coding: utf-8 -*-
"""调用 FastAPI 时的可预期异常（不 import backend.database / services）。"""

from __future__ import annotations

from typing import Any


class BackendAPIError(Exception):
    """HTTP 错误或网络错误后的统一类型。"""

    def __init__(
        self,
        http_status: int,
        code: str | None,
        message: str,
        *,
        raw_detail: Any = None,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.code = code
        self.message = message
        self.raw_detail = raw_detail

    @property
    def is_transport(self) -> bool:
        return self.http_status == 0


def parse_error_detail(detail: Any) -> tuple[str | None, str]:
    """解析 FastAPI HTTPException.detail（str 或 dict）。"""
    if isinstance(detail, list):
        return None, str(detail)
    if isinstance(detail, str):
        return None, detail
    if isinstance(detail, dict):
        code = detail.get("code")
        if isinstance(code, str):
            pass
        else:
            code = None
        msg = detail.get("message") or detail.get("detail") or str(detail)
        if not isinstance(msg, str):
            msg = str(msg)
        return code, msg
    return None, str(detail)
