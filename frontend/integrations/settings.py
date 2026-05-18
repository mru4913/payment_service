# -*- coding: utf-8 -*-
"""Bot 调 FastAPI 的环境配置（与 `backend` 进程解耦，不 import backend.config）。"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BotBackendSettings:
    """后端 HTTP 基址与鉴权。"""

    base_url: str
    api_key: str | None
    connect_timeout: float
    read_timeout: float


def load_bot_backend_settings() -> BotBackendSettings:
    """从环境变量读取；与仓库 `.env` / `API_KEY` 命名对齐。"""
    base = (os.getenv("BACKEND_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
    api_key = os.getenv("API_KEY") or os.getenv("BACKEND_API_KEY")
    if api_key is not None:
        api_key = api_key.strip() or None
    connect = float(os.getenv("BACKEND_HTTP_CONNECT_TIMEOUT", "5"))
    read = float(os.getenv("BACKEND_HTTP_READ_TIMEOUT", "30"))
    return BotBackendSettings(
        base_url=base,
        api_key=api_key,
        connect_timeout=connect,
        read_timeout=read,
    )
