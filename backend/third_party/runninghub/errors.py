# -*- coding: utf-8 -*-
"""RunningHub HTTP / 业务错误。"""

from __future__ import annotations

from typing import Any

# 非 RH 远端返回：客户端未配置或拒绝发送请求时的 ``rh_code`` 哨兵。
MISSING_API_KEY = "MISSING_API_KEY"


class RunningHubAPIError(Exception):
    """请求失败：HTTP 层、传输层或 RH 返回 ``code != 0``。"""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        rh_code: int | str | None = None,
        rh_msg: str | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.rh_code = rh_code
        self.rh_msg = rh_msg
        self.body = body

    def is_retryable(self) -> bool:
        """与客户端内建重试策略对齐的粗粒度判断（供上层编排使用）。"""
        if self.rh_code == MISSING_API_KEY:
            return False
        if self.rh_code is not None:
            return False
        if self.http_status is None:
            return True
        return self.is_retryable_http_status(self.http_status)

    @staticmethod
    def is_retryable_http_status(status: int) -> bool:
        """仅针对已知的 HTTP 状态码（不含 ``None``）。"""
        return status == 408 or status == 429 or status >= 500
