#!/usr/bin/env python
# -*- coding: utf-8 -*-

import hashlib
import secrets
import string
from decimal import Decimal
from typing import Optional


def generate_payment_id() -> str:
    """生成支付ID"""
    return secrets.token_hex(16)


def generate_secure_token(length: int = 32) -> str:
    """生成安全令牌"""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def hash_string(text: str, salt: Optional[str] = None) -> str:
    """字符串哈希"""
    if salt:
        text = text + salt
    return hashlib.sha256(text.encode()).hexdigest()


def validate_amount(amount: Decimal) -> bool:
    """验证金额格式"""
    if amount <= 0:
        return False
    # 检查小数位数（最多4位）
    if amount.as_tuple().exponent < -4:
        return False
    return True


def format_currency(amount: Decimal, currency: str = "USD") -> str:
    """格式化货币显示"""
    return f"{currency} {amount:.2f}"


def round_to_cents(amount: Decimal) -> Decimal:
    """四舍五入到分（2位小数）"""
    return amount.quantize(Decimal("0.01"))


def calculate_fee(amount: Decimal, fee_rate: Decimal = Decimal("0.01")) -> Decimal:
    """计算手续费"""
    return (amount * fee_rate).quantize(Decimal("0.01"))


def is_valid_telegram_id(telegram_id: int) -> bool:
    """验证Telegram ID格式"""
    return isinstance(telegram_id, int) and telegram_id > 0


def sanitize_string(text: str, max_length: int = 255) -> str:
    """清理字符串，移除特殊字符并限制长度"""
    if not text:
        return ""
    # 移除换行符和多余空格
    cleaned = " ".join(text.split())
    return cleaned[:max_length]


def mask_sensitive_data(text: str, visible_chars: int = 4) -> str:
    """掩码敏感数据"""
    if len(text) <= visible_chars:
        return text
    return text[:visible_chars] + "*" * (len(text) - visible_chars)
