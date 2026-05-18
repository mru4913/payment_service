#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
用户相关API路由
"""

import uuid
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException
from decimal import Decimal

from ...services import BalanceBelowHeldError, BalanceService, UserService
from ..dependencies import user_service_read, user_service_write, balance_service_read
from ..schemas.users import UserPatchBody


router = APIRouter(prefix="/users", tags=["users"])


def _user_public_dict(user) -> dict[str, Any]:
    """GET/PATCH 共用的用户 JSON 视图。"""
    prefs = user.preferences
    if prefs is None:
        prefs_out: Any = {}
    elif isinstance(prefs, dict):
        prefs_out = prefs
    else:
        prefs_out = dict(prefs) if hasattr(prefs, "items") else {}

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
        "balance_held": user.balance_held,
        "balance_available": user.balance_available,
        "total_deposits": user.total_deposits,
        "total_withdrawals": user.total_withdrawals,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
        "display_name": user.display_name,
        "preferences": prefs_out,
    }


@router.get("/{telegram_id}")
async def get_user(
    telegram_id: int, user_service: UserService = Depends(user_service_read)
):
    """获取用户信息"""
    user = await user_service.get_user(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    return _user_public_dict(user)


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

    若需更新资料或 preferences，请使用 PATCH /users/{telegram_id}。
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


@router.patch("/{telegram_id}")
async def patch_user(
    telegram_id: int,
    body: UserPatchBody,
    user_service: UserService = Depends(user_service_write),
):
    """更新用户偏好或基本资料（preferences 与库内已有值浅合并）。"""
    user = await user_service.get_user(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    updates: dict[str, Any] = {}
    if body.telegram_username is not None:
        updates["telegram_username"] = body.telegram_username
    if body.first_name is not None:
        updates["first_name"] = body.first_name
    if body.last_name is not None:
        updates["last_name"] = body.last_name
    if body.phone is not None:
        updates["phone"] = body.phone
    if body.preferences is not None:
        base = dict(user.preferences) if user.preferences else {}
        updates["preferences"] = {**base, **body.preferences}

    if not updates:
        return _user_public_dict(user)

    updated = await user_service.update_user(telegram_id, **updates)
    if not updated:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _user_public_dict(updated)


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
    payment_uuid: Optional[uuid.UUID] = None
    if payment_id is not None and str(payment_id).strip() != "":
        try:
            payment_uuid = uuid.UUID(str(payment_id).strip())
        except ValueError as e:
            raise HTTPException(
                status_code=422, detail="payment_id 须为合法 UUID"
            ) from e

    try:
        user = await user_service.update_balance(
            telegram_id=telegram_id,
            amount=amount,
            transaction_type=transaction_type,
            payment_id=payment_uuid,
            description=description,
        )
    except BalanceBelowHeldError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": e.message, "code": e.code},
        ) from e

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
    """获取用户总余额、冻结与可用余额。"""
    user = await user_service.get_user(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    return {
        "telegram_id": telegram_id,
        "balance": user.balance,
        "balance_held": user.balance_held,
        "balance_available": user.balance_available,
    }


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
    """获取用户余额交易记录；`total` 为该用户流水总条数（非本页条数）。"""
    transactions = await balance_service.get_user_transactions(telegram_id, skip, limit)
    total_count = await balance_service.count_user_transactions(telegram_id)

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
                "task_id": str(t.task_id) if t.task_id else None,
                "description": t.description,
                "created_at": t.created_at,
            }
            for t in transactions
        ],
        "total": total_count,
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
