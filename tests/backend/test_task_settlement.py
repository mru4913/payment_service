"""Task 终态后 balance_held 结算逻辑。"""

import uuid
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.domain.task_enums import TaskBalanceHoldStatus
from backend.services.task_service import TaskService, TaskServiceError


def _task(
    status: str,
    charged: Decimal | None = Decimal("2"),
    billable: Decimal | None = Decimal("2"),
) -> MagicMock:
    t = MagicMock()
    t.status = status
    t.charged_amount = charged
    t.billable_seconds = billable
    t.task_type = "face_swap"
    t.priority_type = "lite"
    t.result_payload = None
    t.started_at = datetime(2024, 1, 1, 0, 0, 0)
    t.completed_at = datetime(2024, 1, 1, 0, 0, 2)
    return t


def _hold(active: bool = True, amount: Decimal = Decimal("9")) -> MagicMock:
    h = MagicMock()
    h.status = "active" if active else "released"
    h.amount_usd = amount
    return h


@pytest.mark.asyncio
async def test_settle_skips_when_hold_not_active():
    tid = uuid.uuid4()
    svc = TaskService(AsyncMock())
    svc.task_repo = AsyncMock()
    svc.hold_repo = AsyncMock()
    svc.task_repo.get_by_task_id = AsyncMock(return_value=_task("succeeded"))
    svc.hold_repo.get_by_task_id = AsyncMock(return_value=_hold(active=False))

    with patch.object(svc, "capture_hold_for_task", new_callable=AsyncMock) as cap:
        with patch.object(svc, "release_hold_for_task", new_callable=AsyncMock) as rel:
            await svc.settle_balance_hold_for_terminal_task(tid)
            cap.assert_not_called()
            rel.assert_not_called()


@pytest.mark.asyncio
async def test_settle_succeeded_calls_capture():
    tid = uuid.uuid4()
    svc = TaskService(AsyncMock())
    svc.task_repo = AsyncMock()
    svc.hold_repo = AsyncMock()
    svc.task_repo.get_by_task_id = AsyncMock(
        return_value=_task("succeeded", Decimal("3")),
    )
    svc.hold_repo.get_by_task_id = AsyncMock(return_value=_hold(True))

    with patch.object(svc, "capture_hold_for_task", new_callable=AsyncMock) as cap:
        with patch.object(svc, "release_hold_for_task", new_callable=AsyncMock) as rel:
            await svc.settle_balance_hold_for_terminal_task(tid)
            cap.assert_called_once_with(tid, Decimal("3"))
            rel.assert_not_called()


@pytest.mark.asyncio
async def test_settle_succeeded_computes_charge_when_missing():
    tid = uuid.uuid4()
    svc = TaskService(AsyncMock())
    svc.task_repo = AsyncMock()
    svc.hold_repo = AsyncMock()
    task = _task("succeeded", charged=None, billable=None)
    task.result_payload = {"event_data": {"taskCostTime": "2.1"}}
    svc.task_repo.get_by_task_id = AsyncMock(return_value=task)
    svc.hold_repo.get_by_task_id = AsyncMock(return_value=_hold(True))
    svc.task_repo.update = AsyncMock()

    with patch.object(svc, "capture_hold_for_task", new_callable=AsyncMock) as cap:
        with patch.object(svc, "release_hold_for_task", new_callable=AsyncMock) as rel:
            await svc.settle_balance_hold_for_terminal_task(tid)
            cap.assert_called_once_with(tid, Decimal("0.000600"))
            rel.assert_not_called()
    update_payload = svc.task_repo.update.await_args.args[1]
    assert update_payload["billable_seconds"] == Decimal("3")
    assert update_payload["charged_amount"] == Decimal("0.000600")
    assert update_payload["pricing_version"] == "2026-05-mvp"


@pytest.mark.asyncio
async def test_settle_succeeded_caps_charge_at_hold():
    tid = uuid.uuid4()
    svc = TaskService(AsyncMock())
    svc.task_repo = AsyncMock()
    svc.hold_repo = AsyncMock()
    task = _task("succeeded", charged=None, billable=None)
    task.result_payload = {"event_data": {"taskCostTime": "100"}}
    svc.task_repo.get_by_task_id = AsyncMock(return_value=task)
    svc.hold_repo.get_by_task_id = AsyncMock(return_value=_hold(True, Decimal("0.01")))
    svc.task_repo.update = AsyncMock()

    with patch.object(svc, "capture_hold_for_task", new_callable=AsyncMock) as cap:
        await svc.settle_balance_hold_for_terminal_task(tid)
        cap.assert_called_once_with(tid, Decimal("0.010000"))
    update_payload = svc.task_repo.update.await_args.args[1]
    assert update_payload["charged_amount"] == Decimal("0.010000")
    assert update_payload["result_payload"]["billing"]["charge_capped"] is True


@pytest.mark.asyncio
async def test_settle_failed_calls_release():
    tid = uuid.uuid4()
    svc = TaskService(AsyncMock())
    svc.task_repo = AsyncMock()
    svc.hold_repo = AsyncMock()
    svc.task_repo.get_by_task_id = AsyncMock(return_value=_task("failed"))
    svc.hold_repo.get_by_task_id = AsyncMock(return_value=_hold(True))

    with patch.object(svc, "capture_hold_for_task", new_callable=AsyncMock) as cap:
        with patch.object(svc, "release_hold_for_task", new_callable=AsyncMock) as rel:
            await svc.settle_balance_hold_for_terminal_task(tid)
            rel.assert_called_once_with(tid)
            cap.assert_not_called()


@pytest.mark.asyncio
async def test_settle_failed_sets_zero_charge():
    tid = uuid.uuid4()
    svc = TaskService(AsyncMock())
    svc.task_repo = AsyncMock()
    svc.hold_repo = AsyncMock()
    task = _task("failed", charged=None, billable=None)
    svc.task_repo.get_by_task_id = AsyncMock(return_value=task)
    svc.hold_repo.get_by_task_id = AsyncMock(return_value=_hold(True))
    svc.task_repo.update = AsyncMock()

    with patch.object(svc, "release_hold_for_task", new_callable=AsyncMock) as rel:
        await svc.settle_balance_hold_for_terminal_task(tid)
        rel.assert_called_once_with(tid)
    assert svc.task_repo.update.await_args.args[1] == {
        "billable_seconds": Decimal("0"),
        "charged_amount": Decimal("0"),
    }


@pytest.mark.asyncio
async def test_settle_raises_when_not_terminal():
    tid = uuid.uuid4()
    svc = TaskService(AsyncMock())
    svc.task_repo = AsyncMock()
    svc.task_repo.get_by_task_id = AsyncMock(return_value=_task("running"))

    with pytest.raises(TaskServiceError) as ei:
        await svc.settle_balance_hold_for_terminal_task(tid)
    assert ei.value.code == "task_not_terminal"


def _session_with_begin() -> MagicMock:
    session = MagicMock()
    session.in_transaction.return_value = False
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=None)
    cm.__aexit__ = AsyncMock(return_value=None)
    session.begin = MagicMock(return_value=cm)
    return session


@pytest.mark.asyncio
async def test_release_hold_noop_without_active_hold():
    tid = uuid.uuid4()
    svc = TaskService(_session_with_begin())
    svc.hold_repo.get_by_task_id = AsyncMock(return_value=None)
    await svc.release_hold_for_task(tid)


@pytest.mark.asyncio
async def test_release_hold_noop_when_hold_already_released():
    tid = uuid.uuid4()
    h = MagicMock()
    h.status = TaskBalanceHoldStatus.RELEASED.value
    svc = TaskService(_session_with_begin())
    svc.hold_repo.get_by_task_id = AsyncMock(return_value=h)
    await svc.release_hold_for_task(tid)


@pytest.mark.asyncio
async def test_capture_hold_noop_without_active_hold():
    tid = uuid.uuid4()
    svc = TaskService(_session_with_begin())
    svc.hold_repo.get_by_task_id = AsyncMock(return_value=None)
    await svc.capture_hold_for_task(tid, Decimal("1"))
