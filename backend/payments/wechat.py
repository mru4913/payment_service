#!/usr/bin/env python
# -*- coding: utf-8 -*-

import base64
import hashlib
import json
import time
import uuid
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .base import PaymentProvider, PaymentRequest, PaymentResult, PaymentStatus
from ..globals import settings, logger


def _pem_normalize(pem: str) -> str:
    p = pem.strip()
    if "\\n" in p and "BEGIN" in p:
        p = p.replace("\\n", "\n")
    return p


def decrypt_wechat_notify_resource(
    resource: Dict[str, Any], api_v3_key: str
) -> Dict[str, Any]:
    """解密微信支付 V3 通知 resource（AES-256-GCM）。"""
    if len(api_v3_key.encode("utf-8")) != 32:
        raise ValueError("WECHAT_API_V3_KEY 须为 32 字节字符串")

    nonce = base64.b64decode(resource["nonce"])
    ciphertext = base64.b64decode(resource["ciphertext"])
    ad = (resource.get("associated_data") or "").encode("utf-8")
    key = api_v3_key.encode("utf-8")
    aesgcm = AESGCM(key)
    plain = aesgcm.decrypt(nonce, ciphertext, ad)
    return json.loads(plain.decode("utf-8"))


def verify_wechat_pay_notify_signature(
    raw_body: str, headers: Dict[str, str], platform_cert_pem: str
) -> None:
    """验签失败抛异常。验签串：timestamp\\nnonce\\nbody\\n"""
    ts = headers.get("wechatpay-timestamp") or ""
    nonce = headers.get("wechatpay-nonce") or ""
    sig_b64 = headers.get("wechatpay-signature") or ""
    if not ts or not nonce or not sig_b64:
        raise ValueError("缺少 Wechatpay 签名相关请求头")

    message = f"{ts}\n{nonce}\n{raw_body}\n"
    pem = _pem_normalize(platform_cert_pem)
    pub = serialization.load_pem_public_key(pem.encode("utf-8"))
    sig = base64.b64decode(sig_b64)
    pub.verify(sig, message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())


class WeChatProvider(PaymentProvider):
    """微信支付提供商"""

    def __init__(self):
        self.app_id = settings.wechat_app_id
        self.mch_id = settings.wechat_mch_id
        self.private_key = settings.wechat_private_key
        self.serial_no = settings.wechat_serial_no
        self.api_v3_key = settings.wechat_api_v3_key
        self.platform_cert_pem = settings.wechat_platform_cert_pem
        self.gateway = "https://api.mch.weixin.qq.com/v3/pay/transactions/jsapi"

    @property
    def name(self) -> str:
        return "wechat"

    async def create_payment(self, request: PaymentRequest) -> PaymentResult:
        """创建微信支付订单"""
        try:
            out_trade_no = request.payment_id

            params = {
                "appid": self.app_id,
                "mchid": self.mch_id,
                "out_trade_no": out_trade_no,
                "description": request.description,
                "notify_url": request.callback_url,
                "amount": {
                    "total": int(request.amount_usd * 100),
                    "currency": "CNY",
                },
            }

            timestamp = str(int(self._get_timestamp()))
            nonce_str = str(uuid.uuid4())
            signature = self._generate_sign(params, timestamp, nonce_str)

            headers = {
                "Authorization": (
                    f"WECHATPAY2-SHA256-RSA2048 "
                    f'mchid="{self.mch_id}",'
                    f'serial_no="{self.serial_no}",'
                    f'timestamp="{timestamp}",'
                    f'nonce_str="{nonce_str}",'
                    f'signature="{signature}"'
                ),
                "Content-Type": "application/json",
            }

            return PaymentResult(
                success=True,
                payment_id=request.payment_id,
                external_payment_id=out_trade_no,
                metadata={"params": params, "headers": headers},
            )

        except Exception as e:
            return PaymentResult(
                success=False, payment_id=request.payment_id, error_message=str(e)
            )

    async def query_payment_status(self, payment_id: str) -> PaymentStatus:
        try:
            return PaymentStatus(
                payment_id=payment_id,
                status="pending",
                metadata={"query_method": "wechat_api"},
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
        """微信支付 V3：验签依赖原始 body 与请求头。"""
        cert = self.platform_cert_pem
        if cert and str(cert).strip():
            if raw_body is None or not headers:
                logger.warning("微信回调验签需要 raw_body 与 headers")
                return False
            try:
                verify_wechat_pay_notify_signature(raw_body, headers, cert)
                return True
            except Exception as e:
                logger.warning(f"微信回调验签失败: {e}")
                return False

        if settings.debug or (settings.environment or "").lower() in (
            "dev",
            "development",
            "local",
        ):
            logger.warning("WECHAT_PLATFORM_CERT_PEM 未配置，开发环境跳过微信回调验签")
            return True

        logger.error("生产环境必须配置 WECHAT_PLATFORM_CERT_PEM 以验证微信回调")
        return False

    def decrypt_callback_to_plain(
        self, callback_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """将通知 JSON 解密为明文业务字典（含 out_trade_no、amount 等）。"""
        resource = callback_data.get("resource")
        if not isinstance(resource, dict):
            return callback_data

        if not resource.get("ciphertext"):
            return callback_data

        if not self.api_v3_key:
            raise ValueError("解密微信通知需要配置 WECHAT_API_V3_KEY")

        return decrypt_wechat_notify_resource(resource, self.api_v3_key)

    def _get_timestamp(self) -> float:
        return time.time()

    def _generate_sign(
        self, params: Dict[str, Any], timestamp: str, nonce_str: str
    ) -> str:
        sign_string = (
            f"{timestamp}\n{nonce_str}\n{json.dumps(params, separators=(',', ':'))}\n"
        )
        return hashlib.sha256(sign_string.encode()).hexdigest()
