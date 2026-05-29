"""compute_runner：终态写入与结算衔接。"""

import uuid
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from backend.domain.task_enums import TaskStatus
from backend.workers.compute_runner import (
    promote_task_to_terminal_and_settle,
    run_compute_task_for_worker,
)


def _fake_db_session_context():
    sess_cm = AsyncMock()
    sess_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    sess_cm.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock(return_value=sess_cm)
    return factory


@pytest.mark.asyncio
async def test_promote_skips_settle_when_task_row_missing():
    with patch(
        "backend.workers.compute_runner.async_session_maker",
        _fake_db_session_context(),
    ):
        with patch(
            "backend.workers.compute_runner.settle_task_balance_hold_async",
            new_callable=AsyncMock,
        ) as settle:
            with patch(
                "backend.workers.compute_runner._write_terminal_state",
                new_callable=AsyncMock,
                return_value=False,
            ) as write:
                tid = uuid.uuid4()
                await promote_task_to_terminal_and_settle(tid)
                write.assert_called_once()
                settle.assert_not_called()


@pytest.mark.asyncio
async def test_promote_calls_settle_when_task_row_written():
    with patch(
        "backend.workers.compute_runner.async_session_maker",
        _fake_db_session_context(),
    ):
        with patch(
            "backend.workers.compute_runner.settle_task_balance_hold_async",
            new_callable=AsyncMock,
        ) as settle:
            with patch(
                "backend.workers.compute_runner._write_terminal_state",
                new_callable=AsyncMock,
                return_value=True,
            ):
                tid = uuid.uuid4()
                await promote_task_to_terminal_and_settle(tid)
                settle.assert_called_once_with(tid)


def _session_maker_with_begin():
    """与生产一致：async with session + async with session.begin()。"""
    session = MagicMock()
    begin_cm = MagicMock()
    begin_cm.__aenter__ = AsyncMock(return_value=None)
    begin_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=begin_cm)
    outer = AsyncMock()
    outer.__aenter__ = AsyncMock(return_value=session)
    outer.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=outer)


@pytest.mark.asyncio
async def test_run_compute_retries_until_task_row_visible():
    tid = uuid.uuid4()
    fake_task = SimpleNamespace(
        status=TaskStatus.QUEUED.value,
        celery_task_id=None,
        third_party_platform="other",
    )
    repo_inst = MagicMock()
    repo_inst.get_by_task_id = AsyncMock(
        side_effect=[None, fake_task, fake_task],
    )
    repo_inst.claim_queued_task_for_worker = AsyncMock(return_value=True)
    repo_inst.update = AsyncMock()

    with patch(
        "backend.workers.compute_runner.async_session_maker",
        _session_maker_with_begin(),
    ):
        with patch(
            "backend.workers.compute_runner.TaskRepository",
            return_value=repo_inst,
        ):
            with patch(
                "backend.workers.compute_runner.promote_task_to_terminal_and_settle",
                new_callable=AsyncMock,
            ) as promote:
                with patch(
                    "backend.workers.compute_runner.asyncio.sleep",
                    new_callable=AsyncMock,
                ):
                    await run_compute_task_for_worker(
                        tid, celery_task_id="celery-test-id"
                    )

    assert repo_inst.get_by_task_id.await_count == 3
    repo_inst.claim_queued_task_for_worker.assert_awaited_once_with(
        tid,
        "celery-test-id",
        ANY,
    )
    promote.assert_awaited_once_with(tid)


@pytest.mark.asyncio
async def test_run_compute_skips_when_task_already_claimed():
    tid = uuid.uuid4()
    fake_task = SimpleNamespace(
        status=TaskStatus.QUEUED.value,
        celery_task_id="other-celery-id",
        third_party_platform="runninghub",
    )
    repo_inst = MagicMock()
    repo_inst.get_by_task_id = AsyncMock(return_value=fake_task)
    repo_inst.claim_queued_task_for_worker = AsyncMock(return_value=False)

    with patch(
        "backend.workers.compute_runner.async_session_maker",
        _session_maker_with_begin(),
    ):
        with patch(
            "backend.workers.compute_runner.TaskRepository",
            return_value=repo_inst,
        ):
            with patch(
                "backend.workers.compute_runner._dispatch",
                new_callable=AsyncMock,
            ) as dispatch:
                await run_compute_task_for_worker(tid, celery_task_id="celery-test-id")

    dispatch.assert_not_awaited()
