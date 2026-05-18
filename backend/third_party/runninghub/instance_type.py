# -*- coding: utf-8 -*-
"""从 ``tier_platform_catalog.yaml`` 读取 priority → RunningHub ``instanceType``。"""

from __future__ import annotations

from pathlib import Path

import yaml

_DEFAULT_CATALOG = (
    Path(__file__).resolve().parents[2] / "config" / "tier_platform_catalog.yaml"
)


def load_runninghub_priority_instance_map(
    catalog_path: Path | None = None,
) -> dict[str, str]:
    """返回 ``lite`` / ``default`` / ``plus`` 等键到 RH ``instanceType`` 的映射。"""
    path = catalog_path or _DEFAULT_CATALOG
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = "tier_platform_catalog: root must be a mapping"
        raise ValueError(msg)
    ppm = raw.get("platform_priority_mapping")
    if not isinstance(ppm, dict):
        msg = "tier_platform_catalog: missing platform_priority_mapping"
        raise ValueError(msg)
    rh = ppm.get("runninghub")
    if not isinstance(rh, dict):
        msg = "tier_platform_catalog: missing platform_priority_mapping.runninghub"
        raise ValueError(msg)
    it = rh.get("instance_type")
    if not isinstance(it, dict):
        msg = "tier_platform_catalog: missing runninghub.instance_type"
        raise ValueError(msg)
    out: dict[str, str] = {}
    for k, v in it.items():
        if isinstance(k, str) and isinstance(v, str):
            out[k] = v
        elif isinstance(k, str) and v is not None:
            out[k] = str(v)
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
