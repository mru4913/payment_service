#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
API中间件配置
"""

import time
import uuid
from collections import defaultdict

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ..globals import logger
from common.logger import reset_request_id, set_request_id


class LoggingMiddleware(BaseHTTPMiddleware):
    """请求日志中间件"""

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = set_request_id(request_id)
        request.state.request_id = request_id
        client = request.client.host if request.client else "unknown"

        # 记录请求开始
        logger.info(
            "http_request_start request_id=%s method=%s path=%s client=%s",
            request_id,
            request.method,
            request.url.path,
            client,
        )

        try:
            # 处理请求
            response = await call_next(request)

            # 计算处理时间
            process_time = time.time() - start_time

            # 记录请求完成
            logger.info(
                "http_request_complete request_id=%s method=%s path=%s "
                "status=%s elapsed_ms=%s",
                request_id,
                request.method,
                request.url.path,
                response.status_code,
                int(process_time * 1000),
            )

            # 添加处理时间到响应头
            response.headers["X-Process-Time"] = str(process_time)
            response.headers["X-Request-ID"] = request_id

            return response

        except Exception as e:
            # 记录错误
            process_time = time.time() - start_time
            logger.error(
                "http_request_failed request_id=%s method=%s path=%s "
                "elapsed_ms=%s error=%s",
                request_id,
                request.method,
                request.url.path,
                int(process_time * 1000),
                str(e),
                exc_info=True,
            )
            raise
        finally:
            reset_request_id(token)


def setup_cors_middleware(cors_origins: list[str]) -> dict:
    """配置CORS中间件参数"""
    return {
        "allow_origins": cors_origins,
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }


def setup_trusted_host_middleware(allowed_hosts: list[str]) -> dict:
    """配置信任主机中间件参数"""
    return {"allowed_hosts": allowed_hosts}


class CallbackRateLimitMiddleware(BaseHTTPMiddleware):
    """支付网关回调路径按 IP 滑动窗口限流（内存计数，多实例需网关层限流）。"""

    _window_sec = 60.0
    _hits: defaultdict[str, list[float]] = defaultdict(list)

    def __init__(self, app, max_per_minute: int, path_substring: str = "/callback/"):
        super().__init__(app)
        self.max_per_minute = max(0, max_per_minute)
        self.path_substring = path_substring

    async def dispatch(self, request: Request, call_next):
        if self.max_per_minute > 0 and self.path_substring in request.url.path:
            client = request.client
            ip = client.host if client else "unknown"
            now = time.monotonic()
            cutoff = now - self._window_sec
            hits = self._hits[ip]
            while hits and hits[0] < cutoff:
                hits.pop(0)
            if len(hits) >= self.max_per_minute:
                return JSONResponse(status_code=429, content={"detail": "请求过于频繁"})
            hits.append(now)

        return await call_next(request)
