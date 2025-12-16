#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
API中间件配置
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import time

from ..globals import logger


class LoggingMiddleware(BaseHTTPMiddleware):
    """请求日志中间件"""

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        # 记录请求开始
        logger.info(f"Request started: {request.method} {request.url}")

        try:
            # 处理请求
            response = await call_next(request)

            # 计算处理时间
            process_time = time.time() - start_time

            # 记录请求完成
            logger.info(
                f"Request completed: {request.method} {request.url} - "
                f"Status: {response.status_code} - Time: {process_time:.3f}s"
            )

            # 添加处理时间到响应头
            response.headers["X-Process-Time"] = str(process_time)

            return response

        except Exception as e:
            # 记录错误
            process_time = time.time() - start_time
            logger.error(
                f"Request failed: {request.method} {request.url} - "
                f"Error: {str(e)} - Time: {process_time:.3f}s",
                exc_info=True
            )
            raise


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
    return {
        "allowed_hosts": allowed_hosts
    }
