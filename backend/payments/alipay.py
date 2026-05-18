#!/usr/bin/env python
# -*- coding: utf-8 -*-

import base64
import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from .base import PaymentProvider, PaymentRequest, PaymentResult, PaymentStatus
from ..globals import settings, logger


def _pem_normalize(pem: str) -> str:
    p = pem.strip()
    if "\\n" in p and "BEGIN" in p:
        p = p.replace("\\n", "\n")
    return p


def _alipay_sign_content(params: Dict[str, Any]) -> str:
    """支付宝异步通知验签串：除 sign、sign_type 外按键名 ASCII 升序 & 连接。"""
    parts = []
    for k in sorted(params.keys()):
        if k in ("sign", "sign_type"):
            continue
        v = params[k]
        if v is None or v == "":
            continue
        if isinstance(v, (list, tuple)):
            v = v[0] if v else ""
        parts.append(f"{k}={v}")
    return "&".join(parts)


def verify_alipay_notify_rsa2(
    params: Dict[str, Any], sign_b64: str, public_key_pem: str
) -> bool:
    content = _alipay_sign_content(params)
    pem = _pem_normalize(public_key_pem)
    pub = serialization.load_pem_public_key(pem.encode("utf-8"))
    sig = base64.b64decode(sign_b64)
    pub.verify(sig, content.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return True


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
            params = {
                "app_id": self.app_id,
                "method": "alipay.trade.page.pay",
                "charset": "utf-8",
                "sign_type": "RSA2",
                "timestamp": self._get_timestamp(),
                "version": "1.0",
                "biz_content": json.dumps(
                    {
                        "out_trade_no": request.payment_id,
                        "total_amount": str(request.amount_usd),
                        "subject": request.description,
                        "product_code": "FAST_INSTANT_TRADE_PAY",
                        "notify_url": request.callback_url,
                        "return_url": request.callback_url,
                    }
                ),
            }

            sign = self._generate_sign(params)
            params["sign"] = sign

            payment_url = f"{self.gateway}?{urlencode(params)}"

            return PaymentResult(
                success=True,
                payment_id=request.payment_id,
                payment_url=payment_url,
                metadata={"params": params},
            )

        except Exception as e:
            return PaymentResult(
                success=False, payment_id=request.payment_id, error_message=str(e)
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
                "biz_content": json.dumps({"out_trade_no": payment_id}),
            }

            return PaymentStatus(
                payment_id=payment_id,
                status="pending",
                metadata={"query_params": params},
            )

        except Exception as e:
            return PaymentStatus(
                payment_id=payment_id, status="failed", metadata={"error": str(e)}
            )

    async def cancel_payment(self, payment_id: str) -> bool:
        try:
            return True
        except Exception:
            return False

    async def validate_callback(
        self,
        callback_data: Dict[str, Any],
        *,
        raw_body: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> bool:
        _ = raw_body, headers
        pub = self.public_key
        if not pub or not str(pub).strip():
            logger.warning(
                "ALIPAY_PUBLIC_KEY 未配置，跳过支付宝回调验签（仅适用于本地开发）"
            )
            return True

        params = dict(callback_data)
        sign = params.get("sign")
        if not sign or not isinstance(sign, str):
            return False
        try:
            verify_alipay_notify_rsa2(params, sign, pub)
            return True
        except Exception as e:
            logger.warning(f"支付宝回调验签失败: {e}")
            return False

    def _get_timestamp(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _generate_sign(self, params: Dict[str, Any]) -> str:
        sorted_params = sorted(params.items())
        sign_string = "&".join([f"{k}={v}" for k, v in sorted_params if k != "sign"])
        return hashlib.sha256(sign_string.encode()).hexdigest()
