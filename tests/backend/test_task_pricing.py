"""按秒计费规则。"""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.domain.task_enums import TaskStatus
from backend.services import task_pricing
from backend.services.task_pricing import (
    PriceEntry,
    PricingTable,
    calculate_task_charge,
)


@pytest.fixture(autouse=True)
def _pricing_table(monkeypatch):
    table = PricingTable(
        pricing_version="test-v1",
        prices={
            "face_swap": {
                "lite": PriceEntry(
                    price_per_second_usd=Decimal("0.001000"),
                    pricing_version="test-v1",
                ),
            },
        },
    )
    monkeypatch.setattr(task_pricing, "get_pricing_table", lambda: table)


def _task(**overrides):
    data = {
        "status": TaskStatus.SUCCEEDED.value,
        "task_type": "face_swap",
        "priority_type": "lite",
        "result_payload": None,
        "started_at": datetime(2024, 1, 1, 0, 0, 0),
        "completed_at": datetime(2024, 1, 1, 0, 0, 1),
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_success_uses_upstream_task_cost_time():
    task = _task(result_payload={"event_data": {"taskCostTime": "10.2"}})

    charge = calculate_task_charge(task, Decimal("99"))

    assert charge.billable_seconds == Decimal("11")
    assert charge.charged_amount == Decimal("0.011000")
    assert charge.pricing_version == "test-v1"
    assert charge.capped is False


def test_success_falls_back_to_local_duration():
    task = _task(
        result_payload={},
        started_at=datetime(2024, 1, 1, 0, 0, 0),
        completed_at=datetime(2024, 1, 1, 0, 0, 1, 200000),
    )

    charge = calculate_task_charge(task, Decimal("99"))

    assert charge.billable_seconds == Decimal("2")
    assert charge.charged_amount == Decimal("0.002000")


def test_failed_task_is_not_billed():
    task = _task(status=TaskStatus.FAILED.value)

    charge = calculate_task_charge(task, Decimal("99"))

    assert charge.billable_seconds == Decimal("0")
    assert charge.charged_amount == Decimal("0.000000")
    assert charge.pricing_version is None


def test_charge_is_capped_by_hold_amount():
    task = _task(result_payload={"query": {"taskCostTime": "10"}})

    charge = calculate_task_charge(task, Decimal("0.005000"))

    assert charge.billable_seconds == Decimal("10")
    assert charge.charged_amount == Decimal("0.005000")
    assert charge.capped is True


def test_missing_price_raises():
    task = _task(task_type="unknown")

    with pytest.raises(task_pricing.TaskPricingError) as ei:
        calculate_task_charge(task, Decimal("99"))

    assert ei.value.code == "pricing_not_found"
