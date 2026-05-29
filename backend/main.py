#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
FastAPI应用入口
"""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

from .api.main import create_api_app
from .database.session import create_tables
from .globals import logger, settings
from .payments.trc20_monitor import TRC20Monitor


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("应用启动中...")

    # 初始化数据库表
    try:
        await create_tables()
        logger.info("数据库表创建完成。")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        raise

    # 启动 TRC20 USDT 监控后台任务
    monitor = None
    monitor_task = None
    if settings.trc20_wallet_address:
        monitor = TRC20Monitor(settings)
        monitor_task = asyncio.create_task(monitor.start())

    yield

    # 关闭监控任务
    if monitor:
        await monitor.stop()
    if monitor_task:
        monitor_task.cancel()

    logger.info("应用关闭中...")


# 创建FastAPI应用
app = create_api_app()

# 设置生命周期管理
app.router.lifespan_context = lifespan


# 全局异常处理
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP异常处理器"""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器"""
    logger.error(f"未处理的异常: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "内部服务器错误"})


# 根路径
@app.get("/")
async def root():
    """API根路径"""
    return {
        "message": "Welcome to Eshow (易修) API!",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "health_db": "/health/db",
        "health_detailed": "/health/detailed",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info",
    )
