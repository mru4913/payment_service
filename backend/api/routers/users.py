#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
用户相关API路由
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from decimal import Decimal

from ...services import UserService, BalanceService
from ..dependencies import user_service_read, user_service_write, balance_service_read


router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{telegram_id}")
async def get_user(
    telegram_id: int, user_service: UserService = Depends(user_service_read)
):
    """获取用户信息"""
    user = await user_service.get_user(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    return {
        "telegram_id": user.telegram_id,
        "telegram_username": user.telegram_username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone": user.phone,
        "is_premium": user.is_premium,
        "is_verified": user.is_verified,
        "is_scam": user.is_scam,
        "is_fake": user.is_fake,
        "balance": user.balance,
        "total_deposits": user.total_deposits,
        "total_withdrawals": user.total_withdrawals,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
        "display_name": user.display_name,
    }


@router.post("/{telegram_id}")
async def create_or_update_user(
    telegram_id: int,
    telegram_username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    phone: Optional[str] = None,
    is_premium: bool = False,
    is_verified: bool = False,
    is_scam: bool = False,
    is_fake: bool = False,
    user_service: UserService = Depends(user_service_write),
):
    """创建用户；若已存在则返回当前资料（不根据本次请求更新字段）。

    若需改资料请后续扩展 PATCH 或使用 update_user 接口。
    """
    user, was_created = await user_service.get_or_create_user(
        telegram_id=telegram_id,
        telegram_username=telegram_username,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        is_premium=is_premium,
        is_verified=is_verified,
        is_scam=is_scam,
        is_fake=is_fake,
    )

    return {
        "telegram_id": user.telegram_id,
        "display_name": user.display_name,
        "created": was_created,
    }


@router.put("/{telegram_id}/balance")
async def update_user_balance(
    telegram_id: int,
    amount: Decimal,
    transaction_type: str,
    description: str = "",
    payment_id: Optional[str] = None,
    user_service: UserService = Depends(user_service_write),
):
    """更新用户余额"""
    user = await user_service.update_balance(
        telegram_id=telegram_id,
        amount=amount,
        transaction_type=transaction_type,
        payment_id=payment_id,
        description=description,
    )

    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    return {
        "telegram_id": user.telegram_id,
        "new_balance": user.balance,
        "transaction_type": transaction_type,
    }


@router.get("/{telegram_id}/balance")
async def get_user_balance(
    telegram_id: int, user_service: UserService = Depends(user_service_read)
):
    """获取用户余额"""
    balance = await user_service.get_user_balance(telegram_id)
    if balance is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    return {"telegram_id": telegram_id, "balance_usd": balance}


@router.get("/{telegram_id}/stats")
async def get_user_stats(
    telegram_id: int, user_service: UserService = Depends(user_service_read)
):
    """获取用户统计信息"""
    stats = await user_service.get_user_stats(telegram_id)
    if not stats:
        raise HTTPException(status_code=404, detail="用户不存在")

    return stats


@router.get("/{telegram_id}/transactions")
async def get_user_transactions(
    telegram_id: int,
    skip: int = 0,
    limit: int = 20,
    balance_service: BalanceService = Depends(balance_service_read),
):
    """获取用户余额交易记录"""
    transactions = await balance_service.get_user_transactions(telegram_id, skip, limit)

    return {
        "telegram_id": telegram_id,
        "transactions": [
            {
                "transaction_id": str(t.transaction_id),
                "amount_usd": t.amount_usd,
                "balance_before_usd": t.balance_before_usd,
                "balance_after_usd": t.balance_after_usd,
                "transaction_type": t.transaction_type,
                "payment_id": str(t.payment_id) if t.payment_id else None,
                "description": t.description,
                "created_at": t.created_at,
            }
            for t in transactions
        ],
        "total": len(transactions),
    }


@router.put("/{telegram_id}/deactivate")
async def deactivate_user(
    telegram_id: int, user_service: UserService = Depends(user_service_write)
):
    """停用用户账户"""
    success = await user_service.deactivate_user(telegram_id)
    if not success:
        raise HTTPException(status_code=404, detail="用户不存在")

    return {"message": "用户账户已停用", "telegram_id": telegram_id}


@router.put("/{telegram_id}/activate")
async def activate_user(
    telegram_id: int, user_service: UserService = Depends(user_service_write)
):
    """激活用户账户"""
    success = await user_service.activate_user(telegram_id)
    if not success:
        raise HTTPException(status_code=404, detail="用户不存在")

    return {"message": "用户账户已激活", "telegram_id": telegram_id}
