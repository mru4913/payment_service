#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Bot 启动入口

独立运行：python -m frontend.runner
或由 FastAPI lifespan 以非阻塞方式启动。
"""

import logging

from frontend.bot.bot import build_telegram_app
from frontend.integrations import reset_backend_client

logger = logging.getLogger("frontend.runner")


async def start_bot_polling(app):
    """非阻塞启动 Bot polling（用于 FastAPI lifespan 集成）。"""
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram Bot polling 已启动")


async def stop_bot_polling(app):
    """优雅关闭 Bot polling。"""
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    await reset_backend_client()
    logger.info("Telegram Bot polling 已停止")


def main():
    """独立运行 Bot（阻塞模式）。"""
    app = build_telegram_app()
    logger.info("Telegram Bot 独立模式启动中...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
