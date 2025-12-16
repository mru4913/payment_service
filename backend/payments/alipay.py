#!/usr/bin/env python
# -*- coding: utf-8 -*-

import hashlib
import json
from typing import Dict, Any
from urllib.parse import urlencode

from .base import PaymentProvider, PaymentRequest, PaymentResult, PaymentStatus
from ..globals import settings


class AlipayProvider(PaymentProvider):
    """支付宝支付提供商"""

    def __init__(self):
        self.app_id = settings.alipay_app_id
        self.private_key = settings.alipay_private_key
        self.public_key = settings.alipay_public_key
        self.gateway = "https://openapi.alipay.com/gateway.do"

    @property
    def name(self) -> str:
        return "alipay"

    async def create_payment(self, request: PaymentRequest) -> PaymentResult:
        """创建支付宝支付订单"""
        try:
            # 构建支付参数
            params = {
                "app_id": self.app_id,
                "method": "alipay.trade.page.pay",
                "charset": "utf-8",
                "sign_type": "RSA2",
                "timestamp": self._get_timestamp(),
                "version": "1.0",
                "biz_content": json.dumps({
                    "out_trade_no": request.payment_id,
                    "total_amount": str(request.amount_usd),  # 支付宝期望字符串格式
                    "subject": request.description,
                    "product_code": "FAST_INSTANT_TRADE_PAY",
                    "notify_url": request.callback_url,
                    "return_url": request.callback_url,
                })
            }

            # 生成签名
            sign = self._generate_sign(params)
            params["sign"] = sign

            # 生成支付URL
            payment_url = f"{self.gateway}?{urlencode(params)}"

            return PaymentResult(
                success=True,
                payment_id=request.payment_id,
                payment_url=payment_url,
                metadata={"params": params}
            )

        except Exception as e:
            return PaymentResult(
                success=False,
                payment_id=request.payment_id,
                error_message=str(e)
            )

    async def query_payment_status(self, payment_id: str) -> PaymentStatus:
        """查询支付宝支付状态"""
        try:
            params = {
                "app_id": self.app_id,
                "method": "alipay.trade.query",
                "charset": "utf-8",
                "sign_type": "RSA2",
                "timestamp": self._get_timestamp(),
                "version": "1.0",
                "biz_content": json.dumps({
                    "out_trade_no": payment_id
                })
            }

            # 这里应该发送HTTP请求到支付宝API
            # 暂时返回模拟结果
            return PaymentStatus(
                payment_id=payment_id,
                status="pending",  # 应该从支付宝响应中解析
                metadata={"query_params": params}
            )

        except Exception as e:
            return PaymentStatus(
                payment_id=payment_id,
                status="failed",
                metadata={"error": str(e)}
            )

    async def cancel_payment(self, payment_id: str) -> bool:
        """取消支付宝支付"""
        try:
            # 实现取消支付逻辑
            return True
        except Exception:
            return False

    async def validate_callback(self, callback_data: Dict[str, Any]) -> bool:
        """验证支付宝回调签名"""
        try:
            # 从回调数据中提取签名
            callback_data.pop("sign", "")
            callback_data.pop("sign_type", "RSA2")

            # 重新排序参数
            sorted_params = sorted(callback_data.items())

            # 生成待签名字符串 (暂时未使用，保留以备将来验证)
            "&".join([f"{k}={v}" for k, v in sorted_params])

            # 验证签名（这里需要实现RSA验证逻辑）
            # 暂时返回True
            return True

        except Exception:
            return False

    def _get_timestamp(self) -> str:
        """获取当前时间戳"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _generate_sign(self, params: Dict[str, Any]) -> str:
        """生成RSA2签名"""
        # 这里应该实现RSA2签名逻辑
        # 暂时返回模拟签名
        sorted_params = sorted(params.items())
        sign_string = "&".join([f"{k}={v}" for k, v in sorted_params if k != "sign"])
        return hashlib.sha256(sign_string.encode()).hexdigest()
