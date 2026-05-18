#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""balance_transactions.transaction_type 合法取值（与模型注释、业务写入一致）。"""

from enum import StrEnum


class BalanceTransactionType(StrEnum):
    """余额流水类型 — 写入 DB 时使用 `.value` 或直接使用成员（亦为 str）。"""

    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"
    PAYMENT = "payment"
    REFUND = "refund"
    HOLD = "hold"
    HOLD_RELEASE = "hold_release"
    CONSUMPTION = "consumption"
