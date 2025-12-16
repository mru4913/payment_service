#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
支付相关API路由
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from decimal import Decimal

from ...services import PaymentService
from ..dependencies import payment_service_read, payment_service_write


router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("")
async def create_payment(
    telegram_id: int,
    amount_usd: Decimal,
    payment_method: str,
    description: str = "",
    payment_service: PaymentService = Depends(payment_service_write)
):
    """创建支付订单"""
    if amount_usd <= 0:
        raise HTTPException(status_code=400, detail="支付金额必须大于0")

    payment = await payment_service.create_payment(
        telegram_id=telegram_id,
        amount_usd=amount_usd,
        payment_method=payment_method,
        description=description
    )

    return {
        "payment_id": str(payment.payment_id),
        "telegram_id": payment.telegram_id,
        "amount_usd": payment.amount_usd,
        "payment_method": payment.payment_method,
        "status": payment.status,
        "description": payment.description,
        "created_at": payment.created_at
    }


@router.get("/{payment_id}")
async def get_payment(
    payment_id: str,
    payment_service: PaymentService = Depends(payment_service_read)
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
        "metadata": payment.metadata,
        "created_at": payment.created_at,
        "updated_at": payment.updated_at,
        "completed_at": payment.completed_at
    }


@router.put("/{payment_id}/confirm")
async def confirm_payment(
    payment_id: str,
    external_payment_id: str,
    payment_service: PaymentService = Depends(payment_service_write)
):
    """确认支付完成"""
    payment = await payment_service.confirm_payment(payment_id, external_payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="支付记录不存在或状态不允许确认")

    return {
        "payment_id": str(payment.payment_id),
        "status": payment.status,
        "external_payment_id": payment.external_payment_id,
        "completed_at": payment.completed_at,
        "message": "支付已确认完成"
    }


@router.put("/{payment_id}/cancel")
async def cancel_payment(
    payment_id: str,
    payment_service: PaymentService = Depends(payment_service_write)
):
    """取消支付"""
    payment = await payment_service.cancel_payment(payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="支付记录不存在")

    return {
        "payment_id": str(payment.payment_id),
        "status": payment.status,
        "message": "支付已取消"
    }


@router.put("/{payment_id}/fail")
async def fail_payment(
    payment_id: str,
    reason: str = "支付失败",
    payment_service: PaymentService = Depends(payment_service_write)
):
    """标记支付失败"""
    payment = await payment_service.fail_payment(payment_id, reason)
    if not payment:
        raise HTTPException(status_code=404, detail="支付记录不存在")

    return {
        "payment_id": str(payment.payment_id),
        "status": payment.status,
        "message": "支付已标记为失败"
    }


@router.post("/{payment_id}/refund")
async def process_refund(
    payment_id: str,
    refund_amount: Optional[Decimal] = None,
    payment_service: PaymentService = Depends(payment_service_write)
):
    """处理退款"""
    refund_payment = await payment_service.process_refund(payment_id, refund_amount)
    if not refund_payment:
        raise HTTPException(status_code=400, detail="退款处理失败")

    return {
        "original_payment_id": payment_id,
        "refund_payment_id": str(refund_payment.payment_id),
        "refund_amount_usd": abs(refund_payment.amount_usd),
        "status": "completed",
        "message": "退款已处理"
    }


@router.get("/user/{telegram_id}")
async def get_user_payments(
    telegram_id: int,
    skip: int = 0,
    limit: int = 20,
    payment_service: PaymentService = Depends(payment_service_read)
):
    """获取用户的支付记录"""
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
                "completed_at": p.completed_at
            }
            for p in payments
        ],
        "total": len(payments)
    }


@router.get("/pending")
async def get_pending_payments(
    skip: int = 0,
    limit: int = 100,
    payment_service: PaymentService = Depends(payment_service_read)
):
    """获取待处理的支付"""
    payments = await payment_service.get_pending_payments(skip, limit)

    return {
        "payments": [
            {
                "payment_id": str(p.payment_id),
                "telegram_id": p.telegram_id,
                "amount_usd": p.amount_usd,
                "payment_method": p.payment_method,
                "description": p.description,
                "created_at": p.created_at
            }
            for p in payments
        ],
        "total": len(payments)
    }


@router.get("/status/{status}")
async def get_payments_by_status(
    status: str,
    skip: int = 0,
    limit: int = 100,
    payment_service: PaymentService = Depends(payment_service_read)
):
    """根据状态获取支付记录"""
    if status not in ["pending", "completed", "cancelled", "failed"]:
        raise HTTPException(status_code=400, detail="无效的支付状态")

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
                "created_at": p.created_at
            }
            for p in payments
        ],
        "total": len(payments)
    }
