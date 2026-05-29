#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
支付相关API路由
"""

import json
from typing import Optional, Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Request
from decimal import Decimal

from ...services import PaymentService
from ...payments.callbacks import PaymentCallbackHandler
from ...globals import settings
from ..dependencies import payment_service_read, payment_service_write


router = APIRouter(prefix="/payments", tags=["payments"])

# 支付宝/微信异步通知：第三方无法携带 API Key，单独注册且不在 verify_api_key 保护下
payments_public_router = APIRouter(prefix="/payments", tags=["payments-callback"])
_callback_handler = PaymentCallbackHandler()


@payments_public_router.post("/callback/{payment_method}")
async def payment_gateway_callback(
    payment_method: str, request: Request
) -> Dict[str, Any]:
    """支付平台异步回调（form/json 由平台决定）。"""
    if payment_method not in ("alipay", "wechat"):
        raise HTTPException(status_code=400, detail="不支持的支付方式")

    raw_body: Optional[str] = None
    headers_dict: Optional[Dict[str, str]] = None

    if payment_method == "alipay":
        form = await request.form()
        callback_data = {k: v for k, v in form.multi_items()}
    else:
        body_bytes = await request.body()
        raw_body = body_bytes.decode("utf-8")
        headers_dict = {k.lower(): v for k, v in request.headers.items()}
        try:
            callback_data = json.loads(raw_body)
        except Exception:
            raise HTTPException(status_code=400, detail="无效的 JSON 请求体")

    return await _callback_handler.handle_callback(
        payment_method,
        callback_data,
        raw_body=raw_body,
        headers=headers_dict,
    )


@router.post("")
async def create_payment(
    telegram_id: int,
    amount_usd: Decimal,
    payment_method: str,
    description: str = "",
    payment_service: PaymentService = Depends(payment_service_write),
):
    """创建支付订单。

    ``payment_method == trc20_usdt`` 时由服务端生成唯一链上金额并写入
    ``metadata``；响应含 ``order_timeout_minutes`` 供展示超时提示。
    """
    if amount_usd <= 0:
        raise HTTPException(status_code=400, detail="支付金额必须大于0")

    if payment_method == "trc20_usdt":
        payment, err = await payment_service.create_trc20_usdt_payment(
            telegram_id=telegram_id,
            base_amount_usd=amount_usd,
            description=description,
        )
        if err:
            raise HTTPException(status_code=400, detail=err)
        if payment is None:
            raise HTTPException(status_code=500, detail="TRC20 创建结果异常")
        return {
            "payment_id": str(payment.payment_id),
            "telegram_id": payment.telegram_id,
            "amount_usd": payment.amount_usd,
            "payment_method": payment.payment_method,
            "status": payment.status,
            "description": payment.description,
            "created_at": payment.created_at,
            "metadata": payment.payment_metadata,
            "order_timeout_minutes": settings.trc20_order_timeout_minutes,
        }

    if payment_method == "plisio_invoice":
        payment, err = await payment_service.create_plisio_invoice_payment(
            telegram_id=telegram_id,
            amount_usd=amount_usd,
            description=description,
        )
        if err:
            raise HTTPException(status_code=400, detail=err)
        if payment is None:
            raise HTTPException(status_code=500, detail="Plisio 创建结果异常")
        return _payment_response(payment)

    raise HTTPException(status_code=400, detail="不支持的支付方式")


# 静态 GET 须在 /{payment_id} 之前，否则 pending、status 会被当成 UUID


@router.get("/pending")
async def get_pending_payments(
    skip: int = 0,
    limit: int = 100,
    telegram_id: Optional[int] = None,
    payment_service: PaymentService = Depends(payment_service_read),
):
    """获取待处理的支付；可选 ``telegram_id`` 仅返回该用户的 pending。

    ``total`` 为符合筛选条件的 pending 总条数；``returned`` 为本响应 ``payments``
    条数（≤ ``limit``）。
    """
    total = await payment_service.count_pending_payments(telegram_id)
    payments = await payment_service.get_pending_payments(skip, limit, telegram_id)

    return {
        "payments": [
            {
                "payment_id": str(p.payment_id),
                "telegram_id": p.telegram_id,
                "amount_usd": p.amount_usd,
                "payment_method": p.payment_method,
                "status": p.status,
                "external_payment_id": p.external_payment_id,
                "description": p.description,
                "metadata": p.payment_metadata,
                "created_at": p.created_at,
            }
            for p in payments
        ],
        "total": total,
        "returned": len(payments),
    }


@router.get("/status/{status}")
async def get_payments_by_status(
    status: str,
    skip: int = 0,
    limit: int = 100,
    payment_service: PaymentService = Depends(payment_service_read),
):
    """根据状态获取支付记录。

    ``total`` 为该 ``status`` 下总条数；``returned`` 为本页条数（≤ ``limit``）。
    """
    if status not in ["pending", "completed", "cancelled", "failed"]:
        raise HTTPException(status_code=400, detail="无效的支付状态")

    total = await payment_service.count_payments_by_status(status)
    payments = await payment_service.get_payments_by_status(status, skip, limit)

    return {
        "status": status,
        "payments": [
            {
                "payment_id": str(p.payment_id),
                "telegram_id": p.telegram_id,
                "amount_usd": p.amount_usd,
                "payment_method": p.payment_method,
                "description": p.description,
                "created_at": p.created_at,
            }
            for p in payments
        ],
        "total": total,
        "returned": len(payments),
    }


@router.get("/user/{telegram_id}")
async def get_user_payments(
    telegram_id: int,
    skip: int = 0,
    limit: int = 20,
    payment_service: PaymentService = Depends(payment_service_read),
):
    """获取用户的支付记录。

    ``total`` 为该用户支付记录总条数；``returned`` 为本页条数（≤ ``limit``）。
    """
    total = await payment_service.count_user_payments(telegram_id)
    payments = await payment_service.get_user_payments(telegram_id, skip, limit)

    return {
        "telegram_id": telegram_id,
        "payments": [
            {
                "payment_id": str(p.payment_id),
                "amount_usd": p.amount_usd,
                "payment_method": p.payment_method,
                "status": p.status,
                "external_payment_id": p.external_payment_id,
                "description": p.description,
                "created_at": p.created_at,
                "completed_at": p.completed_at,
            }
            for p in payments
        ],
        "total": total,
        "returned": len(payments),
    }


def _payment_response(payment) -> dict[str, Any]:
    return {
        "payment_id": str(payment.payment_id),
        "telegram_id": payment.telegram_id,
        "amount_usd": payment.amount_usd,
        "payment_method": payment.payment_method,
        "status": payment.status,
        "external_payment_id": payment.external_payment_id,
        "description": payment.description,
        "metadata": payment.payment_metadata,
        "created_at": payment.created_at,
        "updated_at": payment.updated_at,
        "completed_at": payment.completed_at,
    }


@router.get("/{payment_id}")
async def get_payment(
    payment_id: str, payment_service: PaymentService = Depends(payment_service_read)
):
    """获取支付详情"""
    payment = await payment_service.get_payment(payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="支付记录不存在")

    return {
        "payment_id": str(payment.payment_id),
        "telegram_id": payment.telegram_id,
        "amount_usd": payment.amount_usd,
        "payment_method": payment.payment_method,
        "status": payment.status,
        "external_payment_id": payment.external_payment_id,
        "description": payment.description,
        "metadata": payment.payment_metadata,
        "created_at": payment.created_at,
        "updated_at": payment.updated_at,
        "completed_at": payment.completed_at,
    }


@router.put("/{payment_id}/confirm")
async def confirm_payment(
    payment_id: str,
    external_payment_id: str,
    payment_service: PaymentService = Depends(payment_service_write),
):
    """手动确认支付已禁用；支付只能由 provider poll/callback 入账。"""
    _ = payment_id, external_payment_id, payment_service
    raise HTTPException(status_code=403, detail="手动确认支付已禁用")


@router.put("/{payment_id}/cancel")
async def cancel_payment(
    payment_id: str, payment_service: PaymentService = Depends(payment_service_write)
):
    """取消支付"""
    payment = await payment_service.cancel_payment(payment_id)
    if not payment:
        raise HTTPException(
            status_code=404,
            detail="支付记录不存在，或当前状态不允许取消（仅待支付可取消）",
        )

    return {
        "payment_id": str(payment.payment_id),
        "status": payment.status,
        "message": "支付已取消",
    }


@router.put("/{payment_id}/fail")
async def fail_payment(
    payment_id: str,
    reason: str = "支付失败",
    payment_service: PaymentService = Depends(payment_service_write),
):
    """标记支付失败"""
    payment = await payment_service.fail_payment(payment_id, reason)
    if not payment:
        raise HTTPException(
            status_code=404,
            detail="支付记录不存在，或当前状态不允许标记失败（仅待支付可失败）",
        )

    return {
        "payment_id": str(payment.payment_id),
        "status": payment.status,
        "message": "支付已标记为失败",
    }


@router.post("/{payment_id}/refund")
async def process_refund(
    payment_id: str,
    refund_amount: Optional[Decimal] = None,
    payment_service: PaymentService = Depends(payment_service_write),
):
    """HTTP 退款入口已禁用；退款需走独立人工流程。"""
    _ = payment_id, refund_amount, payment_service
    raise HTTPException(status_code=403, detail="HTTP 退款入口已禁用")
