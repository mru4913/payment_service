#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""配方注册表：从 workflow_recipes.yaml 加载 task_type → 工作流映射。

纯逻辑模块（无 IO 除文件读取），便于单元测试。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_RECIPES_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "workflow_recipes.yaml"
)


@dataclass(frozen=True, slots=True)
class NodeSpec:
    """配方中单个节点的映射规则。"""

    node_id: str
    field_name: str
    upload: bool


@dataclass(frozen=True, slots=True)
class WorkflowRecipe:
    """一个 task_type 对应的完整配方。"""

    task_type: str
    platform: str
    workflow_id: str | None
    description: str
    nodes: dict[str, NodeSpec] | None
    estimated_runtime_seconds: int | None = None


def load_recipes(
    path: Path | None = None,
) -> dict[str, WorkflowRecipe]:
    """读取 YAML 并返回 {task_type: WorkflowRecipe}。

    加载失败抛 ``ValueError``，调用方应在启动时 fail-fast。
    """
    p = path or _DEFAULT_RECIPES_PATH
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"workflow_recipes: root must be a mapping, got {type(raw)}")
    recipes_raw = raw.get("recipes")
    if not isinstance(recipes_raw, dict):
        raise ValueError("workflow_recipes: missing or invalid 'recipes' key")

    out: dict[str, WorkflowRecipe] = {}
    for task_type, spec in recipes_raw.items():
        if not isinstance(spec, dict):
            msg = f"workflow_recipes: recipe '{task_type}' must be a mapping"
            raise ValueError(msg)
        out[task_type] = _parse_recipe(task_type, spec)
    return out


def _parse_recipe(task_type: str, spec: dict[str, Any]) -> WorkflowRecipe:
    platform = spec.get("platform")
    if not isinstance(platform, str):
        raise ValueError(f"recipe '{task_type}': platform must be a string")

    wf_id = spec.get("workflow_id")
    if wf_id is not None and not isinstance(wf_id, str):
        raise ValueError(f"recipe '{task_type}': workflow_id must be string or null")

    description = str(spec.get("description", ""))
    estimated_raw = spec.get("estimated_runtime_seconds")
    estimated_runtime_seconds: int | None = None
    if estimated_raw is not None:
        try:
            estimated_runtime_seconds = int(estimated_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"recipe '{task_type}': estimated_runtime_seconds must be int"
            ) from exc
        if estimated_runtime_seconds <= 0:
            raise ValueError(
                f"recipe '{task_type}': estimated_runtime_seconds must be > 0"
            )

    nodes_raw = spec.get("nodes")
    nodes: dict[str, NodeSpec] | None = None
    if nodes_raw is not None:
        if not isinstance(nodes_raw, dict):
            raise ValueError(f"recipe '{task_type}': nodes must be mapping or null")
        nodes = {}
        for key, ns in nodes_raw.items():
            if not isinstance(ns, dict):
                raise ValueError(
                    f"recipe '{task_type}': node '{key}' must be a mapping"
                )
            nodes[key] = NodeSpec(
                node_id=str(ns["node_id"]),
                field_name=str(ns["field_name"]),
                upload=bool(ns.get("upload", False)),
            )

    return WorkflowRecipe(
        task_type=task_type,
        platform=platform,
        workflow_id=wf_id,
        description=description,
        nodes=nodes,
        estimated_runtime_seconds=estimated_runtime_seconds,
    )


def get_recipe(
    task_type: str,
    platform: str,
    *,
    recipes: dict[str, WorkflowRecipe] | None = None,
    path: Path | None = None,
) -> WorkflowRecipe | None:
    """按 task_type 查配方；平台不匹配时返回 None。"""
    if recipes is None:
        recipes = load_recipes(path)
    r = recipes.get(task_type)
    if r is None or r.platform != platform:
        return None
    return r


def normalize_input_payload(
    recipe: WorkflowRecipe,
    input_payload: dict[str, Any],
) -> dict[str, Any]:
    """按 task_type 归一化 payload，保持 API 层简洁。"""
    if recipe.task_type != "face_swap" or "face_images" not in input_payload:
        return dict(input_payload)

    raw_faces = input_payload.get("face_images")
    if not isinstance(raw_faces, list):
        raise ValueError("face_swap: face_images must be a list")
    faces = [str(x).strip() for x in raw_faces if str(x).strip()]
    if not 1 <= len(faces) <= 4:
        raise ValueError("face_swap: face_images must contain 1-4 items")

    target = str(input_payload.get("target_image") or "").strip()
    if not target:
        raise ValueError("face_swap: target_image is required")

    expanded = [faces[i % len(faces)] for i in range(4)]
    out = dict(input_payload)
    for i, ref in enumerate(expanded, start=1):
        out[f"face_image_{i}"] = ref
    out["target_image"] = target
    out["restore"] = bool(input_payload.get("restore", False))
    return out


def build_node_info_list_from_recipe(
    recipe: WorkflowRecipe,
    input_payload: dict[str, Any],
    uploaded_file_names: dict[str, str],
) -> list[dict[str, Any]]:
    """按配方翻译 input_payload 为 RH node_info_list 格式。

    ``uploaded_file_names`` 键为 input_payload 中 upload=true 的字段名，
    值为 upload_media 返回的 fileName。

    返回 ``[{node_id, field_name, field_value}, ...]``。
    """
    if recipe.nodes is None:
        raise ValueError("build_node_info_list_from_recipe: recipe.nodes is None")

    normalized_payload = normalize_input_payload(recipe, input_payload)
    result: list[dict[str, Any]] = []
    for payload_key, spec in recipe.nodes.items():
        if spec.upload:
            fv = uploaded_file_names.get(payload_key)
            if fv is None:
                raise ValueError(f"missing uploaded fileName for '{payload_key}'")
        else:
            fv = normalized_payload.get(payload_key)
            if fv is None:
                raise ValueError(
                    f"input_payload missing required field '{payload_key}'"
                )
        result.append(
            {
                "node_id": spec.node_id,
                "field_name": spec.field_name,
                "field_value": fv,
            }
        )
    return result
