#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
API主入口 - 集成所有路由
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from .routers import (
    users_router,
    payments_router,
    balance_router,
    health_router
)
from .middleware import (
    setup_cors_middleware,
    setup_trusted_host_middleware,
    LoggingMiddleware
)
from ..globals import settings


def create_api_app() -> FastAPI:
    """创建并配置FastAPI应用"""

    app = FastAPI(
        title="TG Payment Bot Backend API",
        description="Telegram支付机器人后端API服务",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json"
    )

    # 添加中间件
    app.add_middleware(LoggingMiddleware)

    # CORS配置
    cors_config = setup_cors_middleware(settings.cors_origins)
    app.add_middleware(
        CORSMiddleware,
        **cors_config
    )

    # Trusted Host配置
    trusted_host_config = setup_trusted_host_middleware(settings.allowed_hosts)
    app.add_middleware(TrustedHostMiddleware, **trusted_host_config)

    # 注册路由
    app.include_router(users_router)
    app.include_router(payments_router)
    app.include_router(balance_router)
    app.include_router(health_router)

    # 根路径
    @app.get("/")
    async def root():
        """API根路径"""
        return {
            "message": "Welcome to TG Payment Bot Backend API",
            "version": "1.0.0",
            "docs": "/docs",
            "health": "/health"
        }

    return app
