#!/usr/bin/env python
# -*- coding: utf-8 -*-

from typing import Dict, Any, Optional
from fastapi import HTTPException

from .alipay import AlipayProvider
from .wechat import WeChatProvider
from ..globals import logger


class PaymentCallbackHandler:
    """支付回调处理器"""

    def __init__(self):
        self.providers = {
            "alipay": AlipayProvider(),
            "wechat": WeChatProvider()
        }

    async def handle_callback(
        self,
        payment_method: str,
        callback_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """处理支付回调"""
        try:
            provider = self.providers.get(payment_method)
            if not provider:
                raise HTTPException(status_code=400, detail="不支持的支付方式")

            # 验证回调签名
            if not await provider.validate_callback(callback_data):
                logger.warning(f"支付回调签名验证失败: {payment_method}")
                raise HTTPException(status_code=400, detail="签名验证失败")

            # 解析回调数据
            payment_info = self._parse_callback_data(payment_method, callback_data)
            if not payment_info:
                raise HTTPException(status_code=400, detail="无效的回调数据")

            # 更新支付状态
            await self._update_payment_status(payment_info)

            # 返回成功响应
            return self._get_success_response(payment_method)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"处理支付回调失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="回调处理失败")

    def _parse_callback_data(
        self,
        payment_method: str,
        callback_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """解析回调数据"""
        try:
            if payment_method == "alipay":
                return self._parse_alipay_callback(callback_data)
            elif payment_method == "wechat":
                return self._parse_wechat_callback(callback_data)
            else:
                return None
        except Exception as e:
            logger.error(f"解析回调数据失败: {e}")
            return None

    def _parse_alipay_callback(self, callback_data: Dict[str, Any]) -> Dict[str, Any]:
        """解析支付宝回调数据"""
        return {
            "payment_id": callback_data.get("out_trade_no"),
            "external_payment_id": callback_data.get("trade_no"),
            "status": (
                "completed"
                if callback_data.get("trade_status") == "TRADE_SUCCESS"
                else "failed"
            ),
            "amount": callback_data.get("total_amount"),
            "payment_method": "alipay"
        }

    def _parse_wechat_callback(self, callback_data: Dict[str, Any]) -> Dict[str, Any]:
        """解析微信支付回调数据"""
        # 从微信回调的resource中解析实际数据
        resource = callback_data.get("resource", {})
        if not resource:
            raise ValueError("无效的微信回调数据")

        # 这里需要根据微信支付回调的具体格式解析
        return {
            "payment_id": resource.get("out_trade_no"),
            "external_payment_id": resource.get("transaction_id"),
            "status": (
                "completed"
                if resource.get("trade_state") == "SUCCESS"
                else "failed"
            ),
            "amount": (
                resource.get("amount", {}).get("total") / 100
                if resource.get("amount")
                else None
            ),  # 转换为元
            "payment_method": "wechat"
        }

    async def _update_payment_status(self, payment_info: Dict[str, Any]):
        """更新支付状态"""

        # 这里需要注入数据库会话，暂时使用简化的方式
        # 在实际使用中，应该通过依赖注入获取db会话
        logger.info(f"更新支付状态: {payment_info}")

        # TODO: 实现实际的数据库更新逻辑
        # await PaymentService.update_payment_status(...)
        # await BalanceService.update_balance(...)

    def _get_success_response(self, payment_method: str) -> Dict[str, Any]:
        """获取成功响应"""
        if payment_method == "alipay":
            return {"code": "success", "message": "success"}
        elif payment_method == "wechat":
            return {"code": "SUCCESS", "message": "成功"}
        else:
            return {"status": "ok"}
