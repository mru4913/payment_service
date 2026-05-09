#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
API路由模块
"""

from .users import router as users_router
from .payments import router as payments_router, payments_public_router
from .balance import router as balance_router
from .health import router as health_router

__all__ = [
    "users_router",
    "payments_router",
    "payments_public_router",
    "balance_router",
    "health_router",
]
