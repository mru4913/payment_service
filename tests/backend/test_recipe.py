#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""backend/workers/recipe.py 单元测试。"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from backend.workers.recipe import (
    NodeSpec,
    WorkflowRecipe,
    build_node_info_list_from_recipe,
    get_recipe,
    load_recipes,
)


@pytest.fixture()
def recipes_path(tmp_path: Path) -> Path:
    p = tmp_path / "recipes.yaml"
    p.write_text(
        textwrap.dedent("""\
        version: 1
        recipes:
          face_swap:
            platform: runninghub
            workflow_id: "wf_face"
            description: "AI 换脸"
            nodes:
              source_image:
                node_id: "12"
                field_name: "image"
                upload: true
              target_image:
                node_id: "15"
                field_name: "image"
                upload: true
        """),
        encoding="utf-8",
    )
    return p


class TestLoadRecipes:
    def test_load_ok(self, recipes_path: Path) -> None:
        recipes = load_recipes(recipes_path)
        assert "face_swap" in recipes
        assert len(recipes) == 1

    def test_face_swap_recipe(self, recipes_path: Path) -> None:
        r = load_recipes(recipes_path)["face_swap"]
        assert r.platform == "runninghub"
        assert r.workflow_id == "wf_face"
        assert r.nodes is not None
        assert len(r.nodes) == 2
        assert r.nodes["source_image"] == NodeSpec("12", "image", True)
        assert r.nodes["target_image"] == NodeSpec("15", "image", True)

    def test_passthrough_recipe(self, tmp_path: Path) -> None:
        """透传配方（nodes null）仍须可被加载；键名与生产 YAML 无关。"""
        p = tmp_path / "passthrough.yaml"
        p.write_text(
            textwrap.dedent("""\
            version: 1
            recipes:
              passthrough_smoke:
                platform: runninghub
                workflow_id: null
                description: "透传"
                nodes: null
            """),
            encoding="utf-8",
        )
        r = load_recipes(p)["passthrough_smoke"]
        assert r.workflow_id is None
        assert r.nodes is None

    def test_invalid_root(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.yaml"
        p.write_text("[]", encoding="utf-8")
        with pytest.raises(ValueError, match="root must be a mapping"):
            load_recipes(p)

    def test_missing_recipes_key(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.yaml"
        p.write_text("version: 1\n", encoding="utf-8")
        with pytest.raises(ValueError, match="missing or invalid 'recipes'"):
            load_recipes(p)

    def test_missing_platform(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.yaml"
        p.write_text(
            textwrap.dedent("""\
            version: 1
            recipes:
              x:
                workflow_id: "abc"
            """),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="platform must be a string"):
            load_recipes(p)


class TestGetRecipe:
    def test_found(self, recipes_path: Path) -> None:
        r = get_recipe("face_swap", "runninghub", path=recipes_path)
        assert r is not None
        assert r.task_type == "face_swap"

    def test_wrong_platform(self, recipes_path: Path) -> None:
        r = get_recipe("face_swap", "other_platform", path=recipes_path)
        assert r is None

    def test_unknown_task_type(self, recipes_path: Path) -> None:
        r = get_recipe("nonexistent", "runninghub", path=recipes_path)
        assert r is None

    def test_with_preloaded(self, recipes_path: Path) -> None:
        loaded = load_recipes(recipes_path)
        r = get_recipe("face_swap", "runninghub", recipes=loaded)
        assert r is not None


class TestBuildNodeInfoList:
    def test_recipe_translation(self) -> None:
        recipe = WorkflowRecipe(
            task_type="face_swap",
            platform="runninghub",
            workflow_id="wf1",
            description="test",
            nodes={
                "source_image": NodeSpec("12", "image", True),
                "prompt": NodeSpec("7", "text", False),
            },
        )
        payload = {"source_image": "url1", "prompt": "hello"}
        uploaded = {"source_image": "uploaded_name.png"}

        result = build_node_info_list_from_recipe(recipe, payload, uploaded)

        assert len(result) == 2
        src = next(n for n in result if n["node_id"] == "12")
        assert src["field_value"] == "uploaded_name.png"
        prm = next(n for n in result if n["node_id"] == "7")
        assert prm["field_value"] == "hello"

    def test_missing_upload_file_name(self) -> None:
        recipe = WorkflowRecipe(
            task_type="t",
            platform="p",
            workflow_id="w",
            description="",
            nodes={"img": NodeSpec("1", "image", True)},
        )
        with pytest.raises(ValueError, match="missing uploaded fileName"):
            build_node_info_list_from_recipe(recipe, {}, {})

    def test_missing_passthrough_field(self) -> None:
        recipe = WorkflowRecipe(
            task_type="t",
            platform="p",
            workflow_id="w",
            description="",
            nodes={"prompt": NodeSpec("1", "text", False)},
        )
        with pytest.raises(ValueError, match="missing required field"):
            build_node_info_list_from_recipe(recipe, {}, {})

    def test_none_nodes_raises(self) -> None:
        recipe = WorkflowRecipe(
            task_type="t",
            platform="p",
            workflow_id=None,
            description="",
            nodes=None,
        )
        with pytest.raises(ValueError, match="nodes is None"):
            build_node_info_list_from_recipe(recipe, {}, {})
