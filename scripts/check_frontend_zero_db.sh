#!/usr/bin/env bash
# 与 tests/frontend/test_frontend_zero_db_imports.py 一致：禁止 frontend 源码 import backend。
set -euo pipefail
cd "$(dirname "$0")/.."
if rg -n '^\s*(from backend\b|import backend\b)' frontend --glob '*.py' 2>/dev/null; then
  echo "错误: frontend 目录下存在对 backend 包的 import，请改为仅通过 HTTP 集成。" >&2
  exit 1
fi
echo "frontend 未发现 import backend。"
