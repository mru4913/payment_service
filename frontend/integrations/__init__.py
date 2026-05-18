# -*- coding: utf-8 -*-
"""Telegram Bot 与 FastAPI 之间的 HTTP 集成（禁止依赖 backend.database / services）。"""

from .backend_client import (
    BackendClient,
    get_backend_client,
    reset_backend_client,
    task_body_for_create,
)
from .backend_errors import BackendAPIError, parse_error_detail
from .settings import BotBackendSettings, load_bot_backend_settings

__all__ = [
    "BackendAPIError",
    "BackendClient",
    "BotBackendSettings",
    "get_backend_client",
    "load_bot_backend_settings",
    "parse_error_detail",
    "reset_backend_client",
    "task_body_for_create",
]
