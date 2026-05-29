# -*- coding: utf-8 -*-
"""从 ``tier_platform_catalog.yaml`` 读取 RunningHub 档位配置。"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

_DEFAULT_CATALOG = (
    Path(__file__).resolve().parents[2] / "config" / "tier_platform_catalog.yaml"
)


def load_runninghub_priority_instance_map(
    catalog_path: Path | None = None,
) -> dict[str, str]:
    """返回 ``lite`` / ``default`` / ``plus`` 等键到 RH ``instanceType`` 的映射。"""
    tiers = _load_runninghub_priority_tiers(catalog_path)
    out: dict[str, str] = {}
    for key, spec in tiers.items():
        instance_type = spec.get("instance_type")
        if isinstance(instance_type, str):
            out[key] = instance_type
        elif instance_type is not None:
            out[key] = str(instance_type)
    return out


def load_runninghub_priority_cost_map(
    catalog_path: Path | None = None,
) -> dict[str, Decimal]:
    """返回内部 priority_type 到 RunningHub 成本价（美元/秒）的映射。"""
    tiers = _load_runninghub_priority_tiers(catalog_path)
    out: dict[str, Decimal] = {}
    for key, spec in tiers.items():
        raw_cost = spec.get("cost_per_second_usd")
        if raw_cost is None:
            msg = f"tier_platform_catalog: missing cost_per_second_usd for {key}"
            raise ValueError(msg)
        try:
            cost = Decimal(str(raw_cost))
        except (InvalidOperation, ValueError) as exc:
            msg = f"tier_platform_catalog: invalid cost_per_second_usd for {key}"
            raise ValueError(msg) from exc
        if cost < 0:
            msg = f"tier_platform_catalog: negative cost_per_second_usd for {key}"
            raise ValueError(msg)
        out[key] = cost
    return out


def _load_runninghub_priority_tiers(
    catalog_path: Path | None = None,
) -> dict[str, dict]:
    path = catalog_path or _DEFAULT_CATALOG
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = "tier_platform_catalog: root must be a mapping"
        raise ValueError(msg)
    platforms = raw.get("platforms")
    if not isinstance(platforms, dict):
        msg = "tier_platform_catalog: missing platforms"
        raise ValueError(msg)
    rh = platforms.get("runninghub")
    if not isinstance(rh, dict):
        msg = "tier_platform_catalog: missing platforms.runninghub"
        raise ValueError(msg)
    tiers = rh.get("priority_tiers")
    if not isinstance(tiers, dict):
        msg = "tier_platform_catalog: missing runninghub.priority_tiers"
        raise ValueError(msg)
    out: dict[str, dict] = {}
    for key, spec in tiers.items():
        if isinstance(key, str) and isinstance(spec, dict):
            out[key] = spec
    return out


def rh_instance_type_for_priority(
    priority: str,
    *,
    catalog_path: Path | None = None,
    mapping: dict[str, str] | None = None,
) -> str | None:
    """将内部 ``PriorityType`` 字符串（如 ``default``）映射为 RH ``instanceType``。"""
    m: dict[str, str]
    if mapping is not None:
        m = mapping
    else:
        m = load_runninghub_priority_instance_map(catalog_path)
    return m.get(priority)
