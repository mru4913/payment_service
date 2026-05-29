#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
InlineKeyboard 定义
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from frontend.core.utils import tr


# ---- Dashboard ----


def dashboard_keyboard(lang: str) -> InlineKeyboardMarkup:
    """首页 Dashboard 操作键盘。"""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"👤 {tr('dashboard.btn_my', lang)}",
                    callback_data="dashboard:my",
                )
            ],
            [
                InlineKeyboardButton(
                    f"💳 {tr('dashboard.btn_recharge', lang)}",
                    callback_data="dashboard:recharge",
                )
            ],
            [
                InlineKeyboardButton(
                    f"🎭 {tr('dashboard.btn_compute', lang)}",
                    callback_data="dashboard:compute",
                )
            ],
            [
                InlineKeyboardButton(
                    f"🖌 {tr('dashboard.btn_remove_watermark', lang)}",
                    callback_data="dashboard:remove_watermark",
                ),
                InlineKeyboardButton(
                    f"📦 {tr('dashboard.btn_batch', lang)}",
                    callback_data="dashboard:batch",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"❓ {tr('dashboard.btn_help', lang)}",
                    callback_data="dashboard:help",
                ),
            ],
        ]
    )


def my_account_keyboard(lang: str) -> InlineKeyboardMarkup:
    """我的页面操作键盘。"""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"📋 {tr('dashboard.btn_history', lang)}",
                    callback_data="dashboard:history",
                ),
                InlineKeyboardButton(
                    f"🗂 {tr('dashboard.btn_task_history', lang)}",
                    callback_data="dashboard:task_history",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"🌐 {tr('dashboard.btn_language', lang)}",
                    callback_data="dashboard:lang",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"↩️ {tr('common.btn_back', lang)}",
                    callback_data="dashboard:home",
                )
            ],
        ]
    )


def account_back_keyboard(lang: str) -> InlineKeyboardMarkup:
    """子页面返回我的页。"""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"↩️ {tr('common.btn_back', lang)}",
                    callback_data="dashboard:my",
                )
            ]
        ]
    )


def home_back_keyboard(
    lang: str,
    *,
    callback_data: str = "dashboard:home",
) -> InlineKeyboardMarkup:
    """子页面返回首页。"""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"↩️ {tr('common.btn_back', lang)}",
                    callback_data=callback_data,
                )
            ]
        ]
    )


# ---- 充值金额选择 ----

RECHARGE_AMOUNTS = [10, 20, 50, 100]


def recharge_amount_keyboard(
    lang: str,
    *,
    back_callback: str | None = "recharge:home",
) -> InlineKeyboardMarkup:
    """充值金额选择键盘"""
    buttons = []
    row = []
    for amt in RECHARGE_AMOUNTS:
        row.append(
            InlineKeyboardButton(f"${amt}", callback_data=f"recharge:amount:{amt}")
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
    if back_callback:
        buttons.append(
            [
                InlineKeyboardButton(
                    f"↩️ {tr('common.btn_back', lang)}",
                    callback_data=back_callback,
                )
            ]
        )
    return InlineKeyboardMarkup(buttons)


def plisio_invoice_keyboard(
    payment_id: str,
    invoice_url: str,
    lang: str,
    *,
    back_callback: str | None = "dashboard:home",
) -> InlineKeyboardMarkup:
    """Plisio invoice 操作键盘：打开支付页 / 刷新状态。"""
    buttons = [
        [
            InlineKeyboardButton(
                tr("recharge.btn_open_invoice", lang),
                url=invoice_url,
            )
        ]
    ]
    buttons.append(
        [
            InlineKeyboardButton(
                tr("common.btn_check_status", lang),
                callback_data=f"recharge:status:{payment_id}",
            )
        ]
    )
    if back_callback:
        buttons.append(
            [
                InlineKeyboardButton(
                    f"↩️ {tr('common.btn_back', lang)}",
                    callback_data=back_callback,
                )
            ]
        )
    return InlineKeyboardMarkup(buttons)


# ---- 语言选择 ----


def language_keyboard(
    lang: str = "zh_hans",
    *,
    back_callback: str | None = None,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("简体中文", callback_data="lang:zh_hans"),
            InlineKeyboardButton("繁體中文", callback_data="lang:zh_hant"),
            InlineKeyboardButton("English", callback_data="lang:en"),
        ]
    ]
    if back_callback:
        rows.append(
            [
                InlineKeyboardButton(
                    f"↩️ {tr('common.btn_back', lang)}",
                    callback_data=back_callback,
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


# ---- 分页 ----


def pagination_keyboard(
    current_page: int,
    total_pages: int,
    prefix: str,
    lang: str,
    *,
    back_callback: str | None = None,
) -> InlineKeyboardMarkup | None:
    """通用分页键盘，返回 None 表示不需要分页。"""
    buttons: list[InlineKeyboardButton] = []
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
    rows = [buttons] if buttons else []
    if back_callback:
        rows.append(
            [
                InlineKeyboardButton(
                    f"↩️ {tr('common.btn_back', lang)}",
                    callback_data=back_callback,
                )
            ]
        )
    return InlineKeyboardMarkup(rows) if rows else None
