#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Bot 启动入口

独立运行：python -m frontend.runner
或由 FastAPI lifespan 以非阻塞方式启动。
"""

from backend.globals import logger
from frontend.payment_bot.bot import build_payment_bot


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
    logger.info("Telegram Bot polling 已停止")


def main():
    """独立运行 Bot（阻塞模式）。"""
    app = build_payment_bot()
    logger.info("Telegram Bot 独立模式启动中...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
