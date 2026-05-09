#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
健康检查API路由
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import time
from datetime import datetime, timezone

from ...database.session import get_db_read


router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """基础健康检查"""
    return {
        "status": "healthy",
        "service": "tg-payment-bot-backend",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
    }


@router.get("/health/db")
async def database_health_check(db: AsyncSession = Depends(get_db_read)):
    """数据库健康检查"""
    start_time = time.time()

    try:
        # 执行简单的数据库查询来测试连接
        from sqlalchemy import text

        await db.execute(text("SELECT 1"))
        response_time = time.time() - start_time

        return {
            "status": "healthy",
            "database": "connected",
            "response_time": f"{response_time:.3f}s",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "database": "disconnected",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@router.get("/health/detailed")
async def detailed_health_check(db: AsyncSession = Depends(get_db_read)):
    """详细健康检查"""
    health_info = {
        "status": "healthy",
        "service": "tg-payment-bot-backend",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {},
    }

    # 数据库检查
    start_time = time.time()
    try:
        from sqlalchemy import text

        await db.execute(text("SELECT COUNT(*) FROM users"))
        db_response_time = time.time() - start_time
        health_info["checks"]["database"] = {
            "status": "healthy",
            "response_time": f"{db_response_time:.3f}s",
        }
    except Exception as e:
        health_info["checks"]["database"] = {"status": "unhealthy", "error": str(e)}
        health_info["status"] = "degraded"

    return health_info
