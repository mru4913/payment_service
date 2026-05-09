#!/usr/bin/env python
# -*- coding: utf-8 -*-

import abc
from decimal import Decimal
from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class PaymentRequest:
    """支付请求"""

    payment_id: str
    amount_usd: Decimal
    description: str
    callback_url: str
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class PaymentResult:
    """支付结果"""

    success: bool
    payment_id: str
    external_payment_id: Optional[str] = None
    payment_url: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class PaymentStatus:
    """支付状态"""

    payment_id: str
    status: str  # pending, completed, failed, cancelled
    external_payment_id: Optional[str] = None
    amount_paid: Optional[Decimal] = None
    metadata: Optional[Dict[str, Any]] = None


class PaymentProvider(abc.ABC):
    """支付提供商抽象基类"""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """支付提供商名称"""
        pass

    @abc.abstractmethod
    async def create_payment(self, request: PaymentRequest) -> PaymentResult:
        """创建支付订单"""
        pass

    @abc.abstractmethod
    async def query_payment_status(self, payment_id: str) -> PaymentStatus:
        """查询支付状态"""
        pass

    @abc.abstractmethod
    async def cancel_payment(self, payment_id: str) -> bool:
        """取消支付"""
        pass

    @abc.abstractmethod
    async def validate_callback(
        self,
        callback_data: Dict[str, Any],
        *,
        raw_body: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> bool:
        """验证回调数据（微信需 raw_body + 请求头验签）。"""
        pass
