#!/usr/bin/env python
# -*- coding: utf-8 -*-

from decimal import Decimal, InvalidOperation
from typing import Dict, Any, Optional

from fastapi import HTTPException

from .alipay import AlipayProvider
from .wechat import WeChatProvider
from .trc20_usdt import TRC20UsdtProvider
from ..database.session import async_session_maker
from ..services.payment_service import PaymentService
from ..globals import logger, settings


class PaymentCallbackHandler:
    """支付回调处理器"""

    def __init__(self):
        self.providers = {
            "alipay": AlipayProvider(),
            "wechat": WeChatProvider(),
            "trc20_usdt": TRC20UsdtProvider(),
        }

    async def handle_callback(
        self,
        payment_method: str,
        callback_data: Dict[str, Any],
        *,
        raw_body: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """处理支付回调"""
        try:
            provider = self.providers.get(payment_method)
            if not provider:
                raise HTTPException(status_code=400, detail="不支持的支付方式")

            if not await provider.validate_callback(
                callback_data, raw_body=raw_body, headers=headers
            ):
                logger.warning(f"支付回调签名验证失败: {payment_method}")
                raise HTTPException(status_code=400, detail="签名验证失败")

            if payment_method == "wechat":
                w = self.providers["wechat"]
                assert isinstance(w, WeChatProvider)
                try:
                    plain = w.decrypt_callback_to_plain(callback_data)
                except ValueError as e:
                    logger.warning(f"微信通知解密失败: {e}")
                    raise HTTPException(status_code=400, detail="回调解密失败") from e
                payment_info = self._parse_wechat_callback(plain)
            else:
                payment_info = self._parse_callback_data(payment_method, callback_data)

            if not payment_info:
                raise HTTPException(status_code=400, detail="无效的回调数据")

            await self._update_payment_status(payment_info)

            return self._get_success_response(payment_method)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"处理支付回调失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="回调处理失败")

    def _parse_callback_data(
        self, payment_method: str, callback_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        try:
            if payment_method == "alipay":
                return self._parse_alipay_callback(callback_data)
            return None
        except Exception as e:
            logger.error(f"解析回调数据失败: {e}")
            return None

    def _parse_alipay_callback(self, callback_data: Dict[str, Any]) -> Dict[str, Any]:
        app_id = settings.alipay_app_id
        if app_id and callback_data.get("app_id") not in (None, "", app_id):
            raise ValueError("支付宝回调 app_id 与配置不一致")

        return {
            "payment_id": callback_data.get("out_trade_no"),
            "external_payment_id": callback_data.get("trade_no"),
            "status": (
                "completed"
                if callback_data.get("trade_status") == "TRADE_SUCCESS"
                else "failed"
            ),
            "amount": callback_data.get("total_amount"),
            "payment_method": "alipay",
        }

    def _parse_wechat_callback(self, plain: Dict[str, Any]) -> Dict[str, Any]:
        """解析微信 V3 解密后的 resource 明文 JSON。"""
        amount_obj = plain.get("amount") or {}
        total_fen = amount_obj.get("total")
        amount_yuan = None
        if total_fen is not None:
            try:
                amount_yuan = int(total_fen) / 100
            except (TypeError, ValueError):
                amount_yuan = None
        return {
            "payment_id": plain.get("out_trade_no"),
            "external_payment_id": plain.get("transaction_id"),
            "status": (
                "completed" if plain.get("trade_state") == "SUCCESS" else "failed"
            ),
            "amount": amount_yuan,
            "payment_method": "wechat",
        }

    async def _update_payment_status(self, payment_info: Dict[str, Any]):
        payment_id = payment_info.get("payment_id")
        external_id = payment_info.get("external_payment_id")
        status = payment_info.get("status")
        amount = payment_info.get("amount")

        if not payment_id or not status:
            logger.warning(f"回调数据缺少必要字段: {payment_info}")
            return

        if status == "completed" and not external_id:
            logger.warning("支付成功回调缺少 external_payment_id，跳过确认以免漏记账务")
            return

        async with async_session_maker() as session:
            async with session.begin():
                svc = PaymentService(session)

                if status == "completed":
                    try:
                        paid_amount = Decimal(str(amount))
                    except (InvalidOperation, TypeError, ValueError):
                        logger.warning(
                            "支付成功回调金额无效，跳过确认: payment_id=%s amount=%s",
                            payment_id,
                            amount,
                        )
                        return
                    payment = await svc.confirm_payment(
                        payment_id,
                        external_id,
                        paid_amount=paid_amount,
                        amount_policy="exact",
                    )
                    if payment:
                        logger.info(
                            f"支付确认成功: payment_id={payment_id}, "
                            f"external_id={external_id}"
                        )
                    else:
                        logger.warning(
                            "支付确认失败(订单不存在或非pending): "
                            f"payment_id={payment_id}"
                        )
                elif status == "failed":
                    failed = await svc.fail_payment(
                        payment_id, "支付平台回调: 支付失败"
                    )
                    if failed:
                        logger.info(f"支付标记失败: payment_id={payment_id}")
                    else:
                        logger.warning(
                            "支付失败回调未改库(订单不存在或非 pending): "
                            f"payment_id={payment_id}"
                        )
                else:
                    await svc.update_payment_status(payment_id, status, external_id)
                    logger.info(
                        f"支付状态更新: payment_id={payment_id}, status={status}"
                    )

    def _get_success_response(self, payment_method: str) -> Dict[str, Any]:
        if payment_method == "alipay":
            return {"code": "success", "message": "success"}
        if payment_method == "wechat":
            return {"code": "SUCCESS", "message": "成功"}
        return {"status": "ok"}
