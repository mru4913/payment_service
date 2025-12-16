#!/usr/bin/env python
# -*- coding: utf-8 -*-

import hashlib
import json
import uuid
from typing import Dict, Any

from .base import PaymentProvider, PaymentRequest, PaymentResult, PaymentStatus
from ..globals import settings


class WeChatProvider(PaymentProvider):
    """微信支付提供商"""

    def __init__(self):
        self.app_id = settings.wechat_app_id
        self.mch_id = settings.wechat_mch_id
        self.private_key = settings.wechat_private_key
        self.serial_no = settings.wechat_serial_no
        self.gateway = "https://api.mch.weixin.qq.com/v3/pay/transactions/jsapi"

    @property
    def name(self) -> str:
        return "wechat"

    async def create_payment(self, request: PaymentRequest) -> PaymentResult:
        """创建微信支付订单"""
        try:
            # 生成微信支付订单号
            out_trade_no = request.payment_id

            # 构建请求参数
            params = {
                "appid": self.app_id,
                "mchid": self.mch_id,
                "out_trade_no": out_trade_no,
                "description": request.description,
                "notify_url": request.callback_url,
                "amount": {
                    "total": int(request.amount_usd * 100),  # 转换为分
                    "currency": "CNY"  # 微信支付使用人民币
                }
            }

            # 生成签名
            timestamp = str(int(self._get_timestamp()))
            nonce_str = str(uuid.uuid4())
            signature = self._generate_sign(params, timestamp, nonce_str)

            # 设置请求头
            headers = {
                "Authorization": (
                    f"WECHATPAY2-SHA256-RSA2048 "
                    f"mchid=\"{self.mch_id}\","
                    f"serial_no=\"{self.serial_no}\","
                    f"timestamp=\"{timestamp}\","
                    f"nonce_str=\"{nonce_str}\","
                    f"signature=\"{signature}\""
                ),
                "Content-Type": "application/json"
            }

            # 这里应该发送HTTP请求到微信支付API
            # 暂时返回模拟结果
            return PaymentResult(
                success=True,
                payment_id=request.payment_id,
                external_payment_id=out_trade_no,
                metadata={"params": params, "headers": headers}
            )

        except Exception as e:
            return PaymentResult(
                success=False,
                payment_id=request.payment_id,
                error_message=str(e)
            )

    async def query_payment_status(self, payment_id: str) -> PaymentStatus:
        """查询微信支付状态"""
        try:
            # 这里应该发送查询请求到微信支付API
            # 暂时返回模拟结果
            return PaymentStatus(
                payment_id=payment_id,
                status="pending",
                metadata={"query_method": "wechat_api"}
            )

        except Exception as e:
            return PaymentStatus(
                payment_id=payment_id,
                status="failed",
                metadata={"error": str(e)}
            )

    async def cancel_payment(self, payment_id: str) -> bool:
        """取消微信支付"""
        try:
            # 实现取消支付逻辑
            return True
        except Exception:
            return False

    async def validate_callback(self, callback_data: Dict[str, Any]) -> bool:
        """验证微信支付回调签名"""
        try:
            # 从回调数据中提取签名信息 (暂时未使用，保留以备将来验证)
            callback_data.get("signature", "")
            callback_data.get("timestamp", "")
            callback_data.get("nonce", "")

            # 验证签名（这里需要实现微信支付签名验证逻辑）
            # 暂时返回True
            return True

        except Exception:
            return False

    def _get_timestamp(self) -> float:
        """获取当前时间戳"""
        import time
        return time.time()

    def _generate_sign(
        self,
        params: Dict[str, Any],
        timestamp: str,
        nonce_str: str
    ) -> str:
        """生成微信支付签名"""
        # 这里应该实现微信支付的签名逻辑
        # 暂时返回模拟签名
        sign_string = (
            f"{timestamp}\n{nonce_str}\n"
            f"{json.dumps(params, separators=(',', ':'))}\n"
        )
        return hashlib.sha256(sign_string.encode()).hexdigest()
