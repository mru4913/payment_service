#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Bot 内部页面导航工具。"""

from typing import Any

from telegram.ext import ContextTypes

from frontend.bot.dashboard_view import dashboard_text_for_user
from frontend.bot.keyboards import dashboard_keyboard


async def edit_to_dashboard_home(
    query: Any,
    context: ContextTypes.DEFAULT_TYPE,
    lang: str,
    *,
    active_panel_keys: tuple[str, ...] = (),
) -> None:
    """将当前 inline message 替换回首页。"""
    user = query.from_user
    if not user:
        return
    for key in active_panel_keys:
        context.user_data.pop(key, None)
    await query.edit_message_text(
        await dashboard_text_for_user(lang, user.id, user.first_name),
        reply_markup=dashboard_keyboard(lang),
        parse_mode="HTML",
    )
