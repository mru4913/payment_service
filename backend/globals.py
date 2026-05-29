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
    name="eshow_backend",
    log_dir=settings.log_dir,
    log_level=settings.log_level or ("DEBUG" if settings.debug else "INFO"),
    max_days=15,
    console=settings.log_to_console,
)
