#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
算力任务与预授权冻结
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from .base_service import BaseService
from ..database.models import BalanceTransaction, Task, TaskBalanceHold
from ..database.repositories import (
    BalanceTransactionRepository,
    TaskBalanceHoldRepository,
    TaskRepository,
    UserRepository,
)
from ..domain.balance_transaction_types import BalanceTransactionType
from ..domain.task_enums import TaskBalanceHoldStatus, TaskStatus
from .task_pricing import calculate_task_charge


class TaskServiceError(Exception):
    """任务域业务错误。"""

    def __init__(self, message: str, code: str = "task_error") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


class TaskService(BaseService):
    """创建 Task、维护 balance_held 与预授权流水。"""

    def __init__(self, db_session: AsyncSession) -> None:
        super().__init__(db_session)
        self.user_repo = UserRepository(db_session)
        self.task_repo = TaskRepository(db_session)
        self.hold_repo = TaskBalanceHoldRepository(db_session)
        self.balance_repo = BalanceTransactionRepository(db_session)

    async def get_task_for_telegram(
        self, task_id: uuid.UUID, telegram_id: int
    ) -> Optional[Task]:
        """校验归属后返回任务。"""
        task = await self.task_repo.get_by_task_id(task_id)
        if not task or task.telegram_id != telegram_id:
            return None
        return task

    async def get_task_by_ref_for_telegram(
        self, task_ref: str, telegram_id: int
    ) -> Optional[Task]:
        """用用户可见短编号查询任务。"""
        return await self.task_repo.get_by_public_task_ref(telegram_id, task_ref)

    async def list_tasks_for_telegram(
        self,
        telegram_id: int,
        *,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Task], int]:
        """用户任务历史分页。"""
        tasks = await self.task_repo.get_user_tasks(
            telegram_id,
            skip=skip,
            limit=limit,
        )
        total = await self.task_repo.count_user_tasks(telegram_id)
        return tasks, total

    async def create_task_with_hold(
        self,
        telegram_id: int,
        task_type: str,
        third_party_platform: str,
        priority_type: str,
        input_payload: Dict[str, Any],
        hold_amount: Decimal,
        task_description: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Tuple[Task, bool]:
        """创建任务并预授权冻结。返回 (task, 是否本次新建)。"""
        if hold_amount <= 0:
            raise TaskServiceError("hold_amount 必须大于 0", "invalid_hold_amount")

        user = await self.user_repo.get_by_telegram_id_for_update(telegram_id)
        if not user:
            raise TaskServiceError("用户不存在", "user_not_found")
        if not user.is_active:
            raise TaskServiceError("用户未激活", "user_inactive")

        if idempotency_key:
            existing = await self.task_repo.get_by_idempotency_key(
                telegram_id, idempotency_key
            )
            if existing:
                return existing, False

        available = user.balance - user.balance_held
        if available < hold_amount:
            raise TaskServiceError("可用余额不足", "insufficient_funds")

        task_id = uuid.uuid4()
        task = Task(
            task_id=task_id,
            telegram_id=telegram_id,
            status=TaskStatus.QUEUED.value,
            task_type=task_type,
            task_description=task_description,
            third_party_platform=third_party_platform,
            priority_type=priority_type,
            input_payload=input_payload,
            idempotency_key=idempotency_key,
        )
        await self.task_repo.create(task)

        hold = TaskBalanceHold(
            hold_id=uuid.uuid4(),
            task_id=task_id,
            telegram_id=telegram_id,
            amount_usd=hold_amount,
            status=TaskBalanceHoldStatus.ACTIVE.value,
        )
        await self.hold_repo.create(hold)

        new_held = user.balance_held + hold_amount
        await self.user_repo.update(user, {"balance_held": new_held})

        tx = BalanceTransaction(
            telegram_id=telegram_id,
            amount_usd=hold_amount,
            balance_before_usd=user.balance,
            balance_after_usd=user.balance,
            transaction_type=BalanceTransactionType.HOLD,
            task_id=task_id,
            description="task pre-authorization hold",
        )
        await self.balance_repo.create(tx)

        return task, True

    async def settle_balance_hold_for_terminal_task(self, task_id: uuid.UUID) -> None:
        """任务已进入终态后结算预授权：成功则 capture，失败/取消则 release。

        若无 active 冻结（已结算或异常数据），静默返回，便于 Worker 重试幂等。
        并发下「先读后写」由 capture/release 事务内再次检查并以空操作保证幂等。
        """
        task = await self.task_repo.get_by_task_id(task_id)
        if not task:
            raise TaskServiceError("任务不存在", "task_not_found")

        terminal = (
            TaskStatus.SUCCEEDED.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
        )
        if task.status not in terminal:
            raise TaskServiceError("任务未处于终态", "task_not_terminal")

        hold = await self.hold_repo.get_by_task_id(task_id)
        if not hold or hold.status != TaskBalanceHoldStatus.ACTIVE.value:
            return

        if task.status == TaskStatus.SUCCEEDED.value:
            captured = await self._ensure_terminal_charge(task, hold)
            await self.capture_hold_for_task(task_id, captured)
        else:
            await self._ensure_zero_charge_for_non_success(task)
            await self.release_hold_for_task(task_id)

    async def _ensure_terminal_charge(
        self,
        task: Task,
        hold: TaskBalanceHold,
    ) -> Decimal:
        """成功终态扣费字段补齐；已有完整扣费字段时保持幂等。"""
        if task.charged_amount is not None and task.billable_seconds is not None:
            captured = task.charged_amount
            if captured > hold.amount_usd:
                captured = hold.amount_usd
                result_payload = dict(task.result_payload or {})
                billing = dict(result_payload.get("billing") or {})
                billing["charge_capped"] = True
                billing["cap_reason"] = "existing_charge_exceeds_hold"
                result_payload["billing"] = billing
                await self.task_repo.update(
                    task,
                    {
                        "charged_amount": captured,
                        "result_payload": result_payload,
                    },
                )
            return captured

        charge = calculate_task_charge(task, hold.amount_usd)
        result_payload = dict(task.result_payload or {})
        if charge.capped:
            billing = dict(result_payload.get("billing") or {})
            billing["charge_capped"] = True
            billing["cap_reason"] = "calculated_charge_exceeds_hold"
            result_payload["billing"] = billing

        payload: dict[str, Any] = {
            "billable_seconds": charge.billable_seconds,
            "charged_amount": charge.charged_amount,
            "pricing_version": charge.pricing_version,
        }
        if charge.capped:
            payload["result_payload"] = result_payload
        await self.task_repo.update(task, payload)
        return charge.charged_amount

    async def _ensure_zero_charge_for_non_success(self, task: Task) -> None:
        """失败 / 取消不计费；已有字段时不重复改写。"""
        payload: dict[str, Any] = {}
        if task.billable_seconds is None:
            payload["billable_seconds"] = Decimal("0")
        if task.charged_amount is None:
            payload["charged_amount"] = Decimal("0")
        if payload:
            await self.task_repo.update(task, payload)

    async def release_hold_for_task(self, task_id: uuid.UUID) -> None:
        """任务失败或取消时释放预授权（不扣总余额）。

        无 active 冻结时直接返回（另一 Worker 已结算等并发场景下幂等）。
        """
        hold = await self.hold_repo.get_by_task_id(task_id)
        if not hold or hold.status != TaskBalanceHoldStatus.ACTIVE.value:
            return

        user = await self.user_repo.get_by_telegram_id_for_update(hold.telegram_id)
        if not user:
            raise TaskServiceError("用户不存在", "user_not_found")

        amt = hold.amount_usd
        new_held = user.balance_held - amt
        if new_held < 0:
            raise TaskServiceError("balance_held 数据异常", "invalid_balance_held")

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.user_repo.update(user, {"balance_held": new_held})
        await self.hold_repo.update(
            hold,
            {
                "status": TaskBalanceHoldStatus.RELEASED.value,
                "released_at": now,
            },
        )

        tx = BalanceTransaction(
            telegram_id=user.telegram_id,
            amount_usd=amt,
            balance_before_usd=user.balance,
            balance_after_usd=user.balance,
            transaction_type=BalanceTransactionType.HOLD_RELEASE,
            task_id=task_id,
            description="task hold released (no capture)",
        )
        await self.balance_repo.create(tx)

    async def capture_hold_for_task(
        self, task_id: uuid.UUID, captured_amount: Decimal
    ) -> None:
        """结算：从总余额扣除实际费用，并释放该任务全部冻结额度。

        无 active 冻结时直接返回（并发重试 / 双 Worker 下幂等）。
        """
        if captured_amount < 0:
            raise TaskServiceError("captured_amount 无效", "invalid_capture_amount")

        hold = await self.hold_repo.get_by_task_id(task_id)
        if not hold or hold.status != TaskBalanceHoldStatus.ACTIVE.value:
            return
        if captured_amount > hold.amount_usd:
            raise TaskServiceError("扣费金额超过冻结上限", "capture_exceeds_hold")

        user = await self.user_repo.get_by_telegram_id_for_update(hold.telegram_id)
        if not user:
            raise TaskServiceError("用户不存在", "user_not_found")

        hold_amt = hold.amount_usd
        old_balance = user.balance
        new_balance = old_balance - captured_amount
        new_held = user.balance_held - hold_amt
        if new_held < 0:
            raise TaskServiceError("balance_held 数据异常", "invalid_balance_held")
        if new_balance < new_held:
            raise TaskServiceError("扣费后总余额低于剩余冻结", "balance_invariant")

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        await self.user_repo.update(
            user,
            {
                "balance": new_balance,
                "balance_held": new_held,
            },
        )

        await self.hold_repo.update(
            hold,
            {
                "status": TaskBalanceHoldStatus.CAPTURED.value,
                "released_at": now,
                "captured_amount_usd": captured_amount,
            },
        )

        cons = BalanceTransaction(
            telegram_id=user.telegram_id,
            amount_usd=-captured_amount,
            balance_before_usd=old_balance,
            balance_after_usd=new_balance,
            transaction_type=BalanceTransactionType.CONSUMPTION,
            task_id=task_id,
            description="task consumption (capture)",
        )
        await self.balance_repo.create(cons)

        rel = BalanceTransaction(
            telegram_id=user.telegram_id,
            amount_usd=hold_amt,
            balance_before_usd=new_balance,
            balance_after_usd=new_balance,
            transaction_type=BalanceTransactionType.HOLD_RELEASE,
            task_id=task_id,
            description="task hold released after capture",
        )
        await self.balance_repo.create(rel)
