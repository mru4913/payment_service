# -*- coding: utf-8 -*-
"""确保 frontend 源码不 import backend 包（零 DB / 进程边界）。"""

import ast
from pathlib import Path


def _iter_import_targets(node: ast.AST) -> list[str]:
    out: list[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            out.append(alias.name)
    elif isinstance(node, ast.ImportFrom) and node.module:
        out.append(node.module)
    return out


def test_frontend_python_files_do_not_import_backend_package() -> None:
    root = Path(__file__).resolve().parents[2] / "frontend"
    bad: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for mod in _iter_import_targets(node):
                if mod == "backend" or mod.startswith("backend."):
                    bad.append(f"{path.relative_to(root.parent)}: {mod}")
    assert not bad, "禁止在 frontend 中 import backend：\n" + "\n".join(bad)
