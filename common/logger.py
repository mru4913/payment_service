#!/usr/bin/env python
# -*- coding: utf-8 -*-


import logging
import logging.handlers
from contextvars import ContextVar, Token
from pathlib import Path

_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    """返回当前异步上下文的 request_id。"""
    return _request_id_var.get()


def set_request_id(request_id: str) -> Token[str]:
    """设置当前异步上下文的 request_id，返回可 reset 的 token。"""
    return _request_id_var.set(request_id or "-")


def reset_request_id(token: Token[str]) -> None:
    """恢复 request_id 上下文。"""
    _request_id_var.reset(token)


class RequestIdFilter(logging.Filter):
    """给日志记录补充 request_id 字段。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class DailyRotatingLogger:
    """每日轮转日志记录器"""

    def __init__(
        self,
        name: str = "eshow",
        log_dir: str = "logs",
        log_level: int = logging.INFO,
        max_days: int = 15,
        console: bool = True,
    ):
        """
        初始化日志记录器

        Args:
            name: 日志记录器名称
            log_dir: 日志文件目录
            log_level: 日志级别
            max_days: 保留日志天数
            console: 是否同时输出到控制台
        """
        self.name = name
        self.log_dir = Path(log_dir)
        self.log_level = log_level
        self.max_days = max_days
        self.console = console

        # 创建日志目录
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # 创建日志记录器
        self.logger = logging.getLogger(name)
        self.logger.setLevel(log_level)

        # 避免重复添加处理器
        if self.logger.handlers:
            return

        self._setup_handlers()

    def _setup_handlers(self):
        """设置日志处理器"""
        # 设置日志格式
        formatter = logging.Formatter(
            fmt=(
                "[%(levelname)-5s] %(asctime)s.%(msecs)03d | rid=%(request_id)s | "
                "%(name)s | %(filename)s:%(lineno)d | "
                "%(funcName)s() | %(message)s"
            ),
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # 文件处理器 - 每天轮转
        log_file = self.log_dir / f"{self.name}.log"
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=str(log_file),
            when="midnight",  # 每天午夜轮转
            interval=1,  # 间隔1天
            backupCount=self.max_days,  # 保留文件数
        )
        file_handler.addFilter(RequestIdFilter())
        file_handler.setFormatter(formatter)
        file_handler.setLevel(self.log_level)
        self.logger.addHandler(file_handler)

        # 控制台处理器
        if self.console:
            console_handler = logging.StreamHandler()
            console_handler.addFilter(RequestIdFilter())
            console_handler.setFormatter(formatter)
            console_handler.setLevel(self.log_level)
            self.logger.addHandler(console_handler)

    @classmethod
    def setup_logging(
        cls,
        name: str = "eshow",
        log_dir: str = "logs",
        log_level: str = "INFO",
        max_days: int = 15,
        console: bool = True,
    ) -> logging.Logger:
        """
        设置日志配置

        Args:
            log_dir: 日志目录
            log_level: 日志级别字符串 ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
            max_days: 保留天数
            console: 是否输出到控制台

        Returns:
            logging.Logger: 配置好的日志记录器
        """
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }

        level = level_map.get(log_level.upper(), logging.INFO)

        return cls(
            name=name,
            log_dir=log_dir,
            log_level=level,
            max_days=max_days,
            console=console,
        ).get_logger()

    def get_logger(self) -> logging.Logger:
        """获取日志记录器实例"""
        return self.logger


# 全局日志实例缓存
_logger_instances: dict[str, DailyRotatingLogger] = {}


def get_logger(
    name: str = "eshow",
    log_dir: str = "logs",
    log_level: int = logging.INFO,
    max_days: int = 15,
    console: bool = True,
) -> logging.Logger:
    """
    获取或创建日志记录器实例

    Args:
        name: 日志记录器名称
        log_dir: 日志文件目录
        log_level: 日志级别
        max_days: 保留日志天数
        console: 是否同时输出到控制台

    Returns:
        logging.Logger: 日志记录器实例
    """
    if name not in _logger_instances:
        _logger_instances[name] = DailyRotatingLogger(
            name=name,
            log_dir=log_dir,
            log_level=log_level,
            max_days=max_days,
            console=console,
        )
    return _logger_instances[name].get_logger()
