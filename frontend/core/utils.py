#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
通用工具函数
"""

import math
from datetime import datetime
from decimal import Decimal
from typing import Optional

from telegram import Update

from .i18n import get_user_lang, t as _t
from backend.database.session import async_session_maker
from backend.services.user_service import UserService


def format_amount(amount: Decimal, decimals: int = 6) -> str:
    """格式化金额，去除尾部多余零。"""
    formatted = f"{amount:.{decimals}f}"
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted


def format_datetime(dt: Optional[datetime]) -> str:
    """格式化时间为可读字符串。"""
    if dt is None:
        return "-"
    return dt.strftime("%Y-%m-%d %H:%M")


def paginate(total: int, page: int, per_page: int = 5) -> tuple[int, int, int]:
    """计算分页参数。

    Returns:
        (total_pages, offset, limit)
    """
    total_pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page
    return total_pages, offset, per_page


async def get_user_lang_from_update(update: Update) -> str:
    """从 Update 中获取用户的语言偏好。"""
    telegram_id = update.effective_user.id
    async with async_session_maker() as session:
        svc = UserService(session)
        user = await svc.get_user(telegram_id)
        if user:
            return get_user_lang(user.preferences)
    return "zh_hans"


def tr(key: str, lang: str, **kwargs) -> str:
    """翻译快捷函数，包装 i18n.t。"""
    return _t(key, lang=lang, **kwargs)
