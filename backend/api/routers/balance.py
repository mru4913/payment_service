#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
余额相关API路由
"""

from fastapi import APIRouter, Depends, HTTPException

from ...services import BalanceService
from ..dependencies import balance_service_read


router = APIRouter(prefix="/balance", tags=["balance"])


@router.get("/transactions/recent")
async def get_recent_transactions(
    days: int = 7,
    skip: int = 0,
    limit: int = 100,
    balance_service: BalanceService = Depends(balance_service_read)
):
    """获取最近的交易记录"""
    if days <= 0 or days > 365:
        raise HTTPException(status_code=400, detail="天数必须在1-365之间")

    transactions = await balance_service.get_recent_transactions(days, skip, limit)

    return {
        "days": days,
        "transactions": [
            {
                "transaction_id": str(t.transaction_id),
                "telegram_id": t.telegram_id,
                "amount_usd": t.amount_usd,
                "balance_before_usd": t.balance_before_usd,
                "balance_after_usd": t.balance_after_usd,
                "transaction_type": t.transaction_type,
                "payment_id": str(t.payment_id) if t.payment_id else None,
                "description": t.description,
                "created_at": t.created_at
            }
            for t in transactions
        ],
        "total": len(transactions)
    }


@router.get("/transactions/type/{transaction_type}")
async def get_transactions_by_type(
    transaction_type: str,
    skip: int = 0,
    limit: int = 100,
    balance_service: BalanceService = Depends(balance_service_read)
):
    """根据交易类型获取记录"""
    valid_types = ["deposit", "withdraw", "payment", "refund"]
    if transaction_type not in valid_types:
        valid_options = ', '.join(valid_types)
        raise HTTPException(
            status_code=400,
            detail=f"无效的交易类型，可选值: {valid_options}"
        )

    transactions = await balance_service.get_transactions_by_type(
        transaction_type, skip, limit
    )

    return {
        "transaction_type": transaction_type,
        "transactions": [
            {
                "transaction_id": str(t.transaction_id),
                "telegram_id": t.telegram_id,
                "amount_usd": t.amount_usd,
                "balance_before_usd": t.balance_before_usd,
                "balance_after_usd": t.balance_after_usd,
                "description": t.description,
                "created_at": t.created_at
            }
            for t in transactions
        ],
        "total": len(transactions)
    }


@router.get("/user/{telegram_id}/summary")
async def get_user_transaction_summary(
    telegram_id: int,
    days: int = 30,
    balance_service: BalanceService = Depends(balance_service_read)
):
    """获取用户交易汇总"""
    if days <= 0 or days > 365:
        raise HTTPException(status_code=400, detail="天数必须在1-365之间")

    summary = await balance_service.get_transaction_summary(telegram_id, days)

    return {
        "telegram_id": telegram_id,
        "period_days": days,
        **summary
    }


@router.get("/transaction/{transaction_id}")
async def get_transaction_by_id(
    transaction_id: str,
    balance_service: BalanceService = Depends(balance_service_read)
):
    """根据交易ID获取记录"""
    transaction = await balance_service.get_transaction_by_id(transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="交易记录不存在")

    return {
        "transaction_id": str(transaction.transaction_id),
        "telegram_id": transaction.telegram_id,
        "amount_usd": transaction.amount_usd,
        "balance_before_usd": transaction.balance_before_usd,
        "balance_after_usd": transaction.balance_after_usd,
        "transaction_type": transaction.transaction_type,
        "payment_id": str(transaction.payment_id) if transaction.payment_id else None,
        "description": transaction.description,
        "created_at": transaction.created_at
    }
