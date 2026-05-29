#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Eshow（易修）Telegram 机器人主程序（支付 + 算力等）。

注册所有 handler，创建 Application 实例。
"""

from telegram.ext import CommandHandler, CallbackQueryHandler

from frontend.core.base_bot import create_bot_application
from frontend.shared.error_handler import error_handler

from .handlers.start import start_handler, help_handler, dashboard_callback
from .handlers.recharge import (
    get_recharge_conversation_handler,
    status_callback,
)
from .handlers.balance import balance_handler
from .handlers.history import history_handler, history_page_callback
from .handlers.task_history import task_history_page_callback
from .handlers.language import lang_handler, lang_callback
from .handlers.compute import (
    compute_global_callback,
    get_compute_conversation_handler,
    task_command,
)
from .handlers.remove_watermark import get_remove_watermark_conversation_handler
from .handlers.batch import batch_global_callback, get_batch_conversation_handler


def build_telegram_app():
    """构建 Telegram Application，注册所有 handler。"""
    app = create_bot_application()

    # 命令
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("balance", balance_handler))
    app.add_handler(CommandHandler("history", history_handler))
    app.add_handler(CommandHandler("task", task_command))
    app.add_handler(CommandHandler("lang", lang_handler))

    app.add_handler(get_compute_conversation_handler())
    app.add_handler(get_remove_watermark_conversation_handler())
    app.add_handler(get_batch_conversation_handler())

    # 充值 ConversationHandler（内含金额选择回调；自定义金额依赖对话状态）
    app.add_handler(get_recharge_conversation_handler())

    # 订单状态（订单消息上的按钮，不依赖对话状态）
    app.add_handler(CallbackQueryHandler(status_callback, pattern=r"^recharge:status:"))

    # 历史分页回调
    app.add_handler(
        CallbackQueryHandler(history_page_callback, pattern=r"^history_page:")
    )
    app.add_handler(
        CallbackQueryHandler(
            task_history_page_callback,
            pattern=r"^task_history_page:",
        )
    )

    # 语言回调
    app.add_handler(CallbackQueryHandler(lang_callback, pattern=r"^lang:"))

    # Dashboard 回调（换脸 / 充值入口由各自 ConversationHandler 接管）
    app.add_handler(
        CallbackQueryHandler(
            dashboard_callback,
            pattern=r"^dashboard:(home|my|history|task_history|lang|help)$",
        )
    )

    # 任务卡片按钮（Conversation 结束后的刷新 / 再做一张）
    app.add_handler(CallbackQueryHandler(compute_global_callback, pattern=r"^compute:"))
    app.add_handler(
        CallbackQueryHandler(batch_global_callback, pattern=r"^batch:(status|history):")
    )

    # 全局错误处理
    app.add_error_handler(error_handler)

    return app
