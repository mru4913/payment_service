#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
全局配置和实例
"""

from .config import Settings
from common.logger import DailyRotatingLogger


# 全局配置实例
settings = Settings()

# 配置日志系统
logger = DailyRotatingLogger.setup_logging(
    name="tg_bot_backend",
    log_dir="logs",
    log_level="DEBUG" if settings.debug else "INFO",
    max_days=15,
    console=True,
)
