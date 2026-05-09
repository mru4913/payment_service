#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
InlineKeyboard 定义
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from frontend.core.utils import tr


# ---- 充值金额选择 ----

RECHARGE_AMOUNTS = [10, 20, 50, 100]


def recharge_amount_keyboard(lang: str) -> InlineKeyboardMarkup:
    """充值金额选择键盘"""
    buttons = []
    row = []
    for amt in RECHARGE_AMOUNTS:
        row.append(
            InlineKeyboardButton(f"{amt} USDT", callback_data=f"recharge:amount:{amt}")
        )
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append(
        [
            InlineKeyboardButton(
                tr("recharge.custom_amount", lang), callback_data="recharge:custom"
            )
        ]
    )
    return InlineKeyboardMarkup(buttons)


def recharge_order_keyboard(payment_id: str, lang: str) -> InlineKeyboardMarkup:
    """充值订单操作键盘（查询状态 / 取消）"""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    tr("common.btn_check_status", lang),
                    callback_data=f"recharge:status:{payment_id}",
                ),
                InlineKeyboardButton(
                    tr("common.btn_cancel", lang),
                    callback_data=f"recharge:cancel:{payment_id}",
                ),
            ]
        ]
    )


# ---- 语言选择 ----


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("简体中文", callback_data="lang:zh_hans"),
                InlineKeyboardButton("繁體中文", callback_data="lang:zh_hant"),
                InlineKeyboardButton("English", callback_data="lang:en"),
            ]
        ]
    )


# ---- 分页 ----


def pagination_keyboard(
    current_page: int, total_pages: int, prefix: str, lang: str
) -> InlineKeyboardMarkup | None:
    """通用分页键盘，返回 None 表示不需要分页。"""
    if total_pages <= 1:
        return None
    buttons = []
    if current_page > 1:
        buttons.append(
            InlineKeyboardButton(
                tr("history.prev", lang), callback_data=f"{prefix}:{current_page - 1}"
            )
        )
    if current_page < total_pages:
        buttons.append(
            InlineKeyboardButton(
                tr("history.next", lang), callback_data=f"{prefix}:{current_page + 1}"
            )
        )
    return InlineKeyboardMarkup([buttons]) if buttons else None
