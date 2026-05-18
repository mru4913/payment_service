#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
通用工具函数
"""

import math
from datetime import datetime
from decimal import Decimal
from typing import Optional, Union

from telegram import Update

from .i18n import (
    get_user_lang,
    get_user_lang_from_telegram,
    t as _t,
)
from frontend.integrations import BackendAPIError, get_backend_client


def format_amount(amount: Decimal, decimals: int = 6) -> str:
    """格式化金额，去除尾部多余零。"""
    formatted = f"{amount:.{decimals}f}"
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted


def format_datetime(dt: Optional[Union[datetime, str]]) -> str:
    """格式化时间为可读字符串（支持 API JSON 的 ISO 字符串）。"""
    if dt is None:
        return "-"
    if isinstance(dt, str):
        try:
            normalized = dt.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return dt[:16] if len(dt) >= 16 else dt
        return parsed.strftime("%Y-%m-%d %H:%M")
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
    """从后端用户 preferences 读取语言；不可用时回退 Telegram language_code。"""
    telegram_id = update.effective_user.id
    client = get_backend_client()
    try:
        user = await client.get_user(telegram_id)
        return get_user_lang(user.get("preferences"))
    except BackendAPIError as e:
        if e.http_status == 404:
            return get_user_lang_from_telegram(update.effective_user)
        if e.is_transport or e.http_status in (401, 403):
            return get_user_lang_from_telegram(update.effective_user)
        raise


def tr(key: str, lang: str, **kwargs) -> str:
    """翻译快捷函数，包装 i18n.t。"""
    return _t(key, lang=lang, **kwargs)
