#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
API 鉴权 - API Key 验证

通过 X-API-Key header 验证请求。
若未配置 API_KEY 环境变量，则跳过鉴权（开发模式）。
"""

from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader

from ..globals import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str | None = Security(_api_key_header)):
    """验证 API Key。未配置时放行（开发模式）。"""
    if not settings.api_key:
        return

    if not api_key or api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key",
        )
