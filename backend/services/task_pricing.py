#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""算力任务按秒计费。

计费策略：
- 仅 succeeded 任务扣费；failed / cancelled 计 0 并释放冻结。
- 上游耗时字段优先；缺失时回退本地 started_at → completed_at。
- 价格由 backend/config/pricing_table.yaml 按 task_type + priority_type 配置。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import yaml

from ..domain.task_enums import TaskStatus

_PRICING_PATH = Path(__file__).resolve().parents[1] / "config" / "pricing_table.yaml"
_USD_QUANT = Decimal("0.000001")
_DURATION_KEYS = (
    "taskCostTime",
    "task_cost_time",
    "billableSeconds",
    "billable_seconds",
    "durationSeconds",
    "duration_seconds",
)
_pricing_cache: "PricingTable | None" = None


class TaskPricingError(Exception):
    """计费配置或时长计算异常。"""

    def __init__(self, message: str, code: str = "pricing_error") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class PriceEntry:
    price_per_second_usd: Decimal
    pricing_version: str


@dataclass(frozen=True)
class PricingTable:
    pricing_version: str
    prices: dict[str, dict[str, PriceEntry]]


@dataclass(frozen=True)
class TaskCharge:
    billable_seconds: Decimal
    charged_amount: Decimal
    pricing_version: str | None
    capped: bool = False


def clear_pricing_cache() -> None:
    """测试或热更新配置后清空缓存。"""
    global _pricing_cache  # noqa: PLW0603
    _pricing_cache = None


def load_pricing_table(path: Path = _PRICING_PATH) -> PricingTable:
    """加载按 task_type + priority_type 计费表。"""
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise TaskPricingError("pricing_table.yaml root must be a mapping")

    version = str(raw.get("pricing_version") or raw.get("version") or "").strip()
    if not version:
        raise TaskPricingError("pricing_table.yaml missing pricing_version")

    raw_prices = raw.get("prices")
    if not isinstance(raw_prices, dict):
        raise TaskPricingError("pricing_table.yaml missing prices")

    prices: dict[str, dict[str, PriceEntry]] = {}
    for task_type, raw_tiers in raw_prices.items():
        if not isinstance(raw_tiers, dict):
            continue
        tier_prices: dict[str, PriceEntry] = {}
        for priority_type, raw_entry in raw_tiers.items():
            if not isinstance(raw_entry, dict) or not raw_entry.get("enabled", True):
                continue
            raw_price = raw_entry.get("price_per_second_usd")
            if raw_price is None:
                raise TaskPricingError(
                    f"missing price_per_second_usd for {task_type}/{priority_type}"
                )
            try:
                price = Decimal(str(raw_price))
            except (InvalidOperation, ValueError) as exc:
                raise TaskPricingError(
                    f"invalid price_per_second_usd for {task_type}/{priority_type}"
                ) from exc
            if price < 0:
                raise TaskPricingError(
                    f"negative price_per_second_usd for {task_type}/{priority_type}"
                )
            tier_prices[str(priority_type)] = PriceEntry(
                price_per_second_usd=price,
                pricing_version=str(raw_entry.get("pricing_version") or version),
            )
        prices[str(task_type)] = tier_prices

    return PricingTable(pricing_version=version, prices=prices)


def get_pricing_table() -> PricingTable:
    global _pricing_cache  # noqa: PLW0603
    if _pricing_cache is None:
        _pricing_cache = load_pricing_table()
    return _pricing_cache


def get_price_entry(task_type: str, priority_type: str) -> PriceEntry:
    table = get_pricing_table()
    entry = table.prices.get(task_type, {}).get(priority_type)
    if entry is None:
        raise TaskPricingError(
            "missing enabled price for "
            f"task_type={task_type} priority_type={priority_type}",
            "pricing_not_found",
        )
    return entry


def _decimal_from_any(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        duration = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if duration < 0:
        return None
    return duration


def _walk_duration(value: Any) -> Decimal | None:
    if isinstance(value, dict):
        for key in _DURATION_KEYS:
            if key in value:
                parsed = _decimal_from_any(value[key])
                if parsed is not None:
                    return parsed
        for child in value.values():
            parsed = _walk_duration(child)
            if parsed is not None:
                return parsed
    elif isinstance(value, list):
        for child in value:
            parsed = _walk_duration(child)
            if parsed is not None:
                return parsed
    return None


def _ceil_seconds(seconds: Decimal) -> Decimal:
    return seconds.to_integral_value(rounding=ROUND_CEILING)


def _local_duration_seconds(
    started_at: datetime | None,
    completed_at: datetime | None,
) -> Decimal:
    if started_at is None or completed_at is None:
        return Decimal("0")
    elapsed = Decimal(str((completed_at - started_at).total_seconds()))
    if elapsed <= 0:
        return Decimal("0")
    return elapsed


def calculate_task_charge(task: Any, hold_amount: Decimal) -> TaskCharge:
    """根据任务终态与价目表计算扣费。"""
    if task.status != TaskStatus.SUCCEEDED.value:
        return TaskCharge(
            billable_seconds=Decimal("0"),
            charged_amount=Decimal("0.000000"),
            pricing_version=None,
        )

    entry = get_price_entry(str(task.task_type), str(task.priority_type))
    upstream_seconds = _walk_duration(task.result_payload)
    raw_seconds = (
        upstream_seconds
        if upstream_seconds is not None
        else _local_duration_seconds(task.started_at, task.completed_at)
    )
    billable_seconds = _ceil_seconds(raw_seconds)
    raw_charge = Decimal(billable_seconds) * entry.price_per_second_usd
    charged_amount = raw_charge.quantize(_USD_QUANT, rounding=ROUND_HALF_UP)
    capped = charged_amount > hold_amount
    if capped:
        charged_amount = hold_amount.quantize(_USD_QUANT, rounding=ROUND_HALF_UP)

    return TaskCharge(
        billable_seconds=Decimal(billable_seconds),
        charged_amount=charged_amount,
        pricing_version=entry.pricing_version,
        capped=capped,
    )
