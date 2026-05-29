"""算力客户标价档位与 workflow 估算配置。

该模块不依赖 backend/frontend 包，用于在 Bot 与后端之间共享同一套
「客户标价档位单价 + workflow 预计运行秒数」规则。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIER_CATALOG_PATH = _ROOT / "backend" / "config" / "tier_platform_catalog.yaml"
DEFAULT_WORKFLOW_RECIPES_PATH = _ROOT / "backend" / "config" / "workflow_recipes.yaml"
USD_QUANT = Decimal("0.000001")


class ComputeCatalogError(Exception):
    """算力配置缺失或格式错误。"""


@dataclass(frozen=True)
class PriorityTier:
    key: str
    price_per_second_usd: Decimal
    pricing_version: str
    enabled: bool = True


def _read_yaml(path: Path) -> dict:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ComputeCatalogError(f"{path.name}: root must be a mapping")
    return raw


@lru_cache(maxsize=8)
def load_priority_tiers(
    path: Path = DEFAULT_TIER_CATALOG_PATH,
) -> dict[str, PriorityTier]:
    """读取 priority_tiers 中启用的客户标价单位时间价格。"""
    raw = _read_yaml(path)
    pricing_version = str(
        raw.get("pricing_version") or raw.get("version") or ""
    ).strip()
    if not pricing_version:
        raise ComputeCatalogError(f"{path.name}: missing pricing_version")

    tiers_raw = raw.get("priority_tiers")
    if not isinstance(tiers_raw, dict):
        raise ComputeCatalogError(f"{path.name}: missing priority_tiers")

    tiers: dict[str, PriorityTier] = {}
    for key, spec in tiers_raw.items():
        if not isinstance(spec, dict):
            continue
        if not spec.get("enabled", True):
            continue
        raw_price = spec.get("price_per_second_usd")
        if raw_price is None:
            raise ComputeCatalogError(
                f"{path.name}: missing price_per_second_usd for {key}"
            )
        try:
            price = Decimal(str(raw_price))
        except (InvalidOperation, ValueError) as exc:
            raise ComputeCatalogError(
                f"{path.name}: invalid price_per_second_usd for {key}"
            ) from exc
        if price < 0:
            raise ComputeCatalogError(
                f"{path.name}: negative price_per_second_usd for {key}"
            )
        tiers[str(key)] = PriorityTier(
            key=str(key),
            price_per_second_usd=price,
            pricing_version=str(spec.get("pricing_version") or pricing_version),
            enabled=True,
        )
    return tiers


@lru_cache(maxsize=8)
def load_workflow_estimates(
    path: Path = DEFAULT_WORKFLOW_RECIPES_PATH,
) -> dict[str, Decimal]:
    """读取每个 workflow 的预计运行秒数。"""
    raw = _read_yaml(path)
    recipes_raw = raw.get("recipes")
    if not isinstance(recipes_raw, dict):
        raise ComputeCatalogError(f"{path.name}: missing recipes")

    estimates: dict[str, Decimal] = {}
    for task_type, spec in recipes_raw.items():
        if not isinstance(spec, dict):
            continue
        raw_seconds = spec.get("estimated_runtime_seconds")
        if raw_seconds is None:
            raise ComputeCatalogError(
                f"{path.name}: missing estimated_runtime_seconds for {task_type}"
            )
        try:
            seconds = Decimal(str(raw_seconds))
        except (InvalidOperation, ValueError) as exc:
            raise ComputeCatalogError(
                f"{path.name}: invalid estimated_runtime_seconds for {task_type}"
            ) from exc
        if seconds <= 0:
            raise ComputeCatalogError(
                f"{path.name}: estimated_runtime_seconds must be > 0 for {task_type}"
            )
        estimates[str(task_type)] = seconds
    return estimates


def estimate_hold_amount(
    task_type: str,
    priority_type: str,
    *,
    tier_catalog_path: Path = DEFAULT_TIER_CATALOG_PATH,
    workflow_recipes_path: Path = DEFAULT_WORKFLOW_RECIPES_PATH,
) -> Decimal:
    """预冻结金额 = workflow 预计秒数 × priority 档位客户标价秒单价。"""
    tiers = load_priority_tiers(tier_catalog_path)
    tier = tiers.get(priority_type)
    if tier is None:
        raise ComputeCatalogError(f"missing priority tier: {priority_type}")

    estimates = load_workflow_estimates(workflow_recipes_path)
    seconds = estimates.get(task_type)
    if seconds is None:
        raise ComputeCatalogError(f"missing workflow estimate: {task_type}")

    return (seconds * tier.price_per_second_usd).quantize(
        USD_QUANT,
        rounding=ROUND_HALF_UP,
    )


def clear_compute_catalog_cache() -> None:
    """测试或热更新配置后清空缓存。"""
    load_priority_tiers.cache_clear()
    load_workflow_estimates.cache_clear()
