#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""端到端：POST /tasks（universal_edit）+ 轮询状态；可选 query RunningHub。

容器内 Worker 读图请使用挂载路径，例如 ``/dataset/20260509-111208.jpg``。

用法（仓库根目录，已 ``source .env`` 或导出变量）::

    uv run python scripts/smoke_universal_edit_runninghub.py

环境变量：
    SMOKE_API_BASE      默认 ``http://127.0.0.1:8000``
    SMOKE_IMAGE_PATH    默认 ``/dataset/20260509-111208.jpg``
    SMOKE_TELEGRAM_ID   默认 ``999888822``
    SMOKE_OUTPUT_MD     默认 ``tmp/runninghub_universal_edit_smoke.md``
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.globals import settings  # noqa: E402
from backend.third_party.runninghub import get_runninghub_client  # noqa: E402


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_md(path: Path, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\n## {_utc_iso()} — {title}\n\n")
        f.write(body.rstrip() + "\n")


def _json_block(obj: Any) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, indent=2)
    except TypeError:
        s = repr(obj)
    return "```json\n" + s + "\n```\n"


def _resp_json(resp: httpx.Response) -> Any:
    return resp.json() if resp.content else {}


async def _rh_query_once(upstream_task_id: str) -> dict[str, Any]:
    client = get_runninghub_client(settings)
    try:
        q = await client.query_task(upstream_task_id)
        return {
            "status": q.status,
            "error_code": q.error_code,
            "error_message": q.error_message,
            "raw": q.raw,
        }
    finally:
        await client.aclose()


def main() -> int:
    base = os.environ.get("SMOKE_API_BASE", "http://127.0.0.1:8000").rstrip("/")
    image_path = os.environ.get("SMOKE_IMAGE_PATH", "/dataset/20260509-111208.jpg")
    telegram_id = int(os.environ.get("SMOKE_TELEGRAM_ID", "999888822"))
    default_md = "tmp/runninghub_universal_edit_smoke.md"
    out_md = Path(os.environ.get("SMOKE_OUTPUT_MD", default_md))
    workflow_id = "2054766030395854850"
    api_key = os.environ.get("API_KEY", "")

    out_md.write_text(
        f"# RunningHub 万能编辑冒烟\n\n"
        f"- 生成时间（UTC）：{_utc_iso()}\n"
        f"- API：{base}\n"
        f"- workflow_id：`{workflow_id}`\n"
        f"- 图片路径：`{image_path}`\n",
        encoding="utf-8",
    )

    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key

    with httpx.Client(timeout=120.0) as http:
        r_user = http.post(f"{base}/users/{telegram_id}", headers=headers)
        uj = _resp_json(r_user)
        _append_md(
            out_md,
            "POST /users/{id}",
            f"HTTP {r_user.status_code}\n\n{_json_block(uj)}",
        )

        r_bal = http.put(
            f"{base}/users/{telegram_id}/balance",
            headers=headers,
            params={
                "amount": str(Decimal("50")),
                "transaction_type": "deposit",
                "description": "smoke_universal_edit",
            },
        )
        bj = _resp_json(r_bal)
        _append_md(
            out_md,
            "PUT /users/{id}/balance",
            f"HTTP {r_bal.status_code}\n\n{_json_block(bj)}",
        )
        if r_bal.status_code >= 400:
            print("balance adjust failed", r_bal.text)
            return 1

        payload = {
            "telegram_id": telegram_id,
            "task_type": "universal_edit",
            "third_party_platform": "runninghub",
            "priority_type": "lite",
            "hold_amount": "0.5",
            "task_description": "万能编辑 smoke",
            "input_payload": {
                "workflow_id": workflow_id,
                "image": image_path,
                "prompt": "换一套比基尼",
            },
        }
        r_task = http.post(f"{base}/tasks", headers=headers, json=payload)
        tj = _resp_json(r_task)
        _append_md(
            out_md,
            "POST /tasks",
            f"HTTP {r_task.status_code}\n\n{_json_block(tj)}",
        )
        if r_task.status_code >= 400:
            print("create task failed", r_task.text)
            return 1
        task_body = r_task.json()
        task_id = task_body.get("task_id")
        if not task_id:
            print("missing task_id in response")
            return 1

        upstream: str | None = None
        deadline = time.monotonic() + 180.0
        last_status: dict[str, Any] = {}
        while time.monotonic() < deadline:
            rs = http.get(
                f"{base}/tasks/{task_id}",
                headers=headers,
                params={"telegram_id": telegram_id},
            )
            last_status = rs.json() if rs.content else {}
            sj = _resp_json(rs)
            _append_md(
                out_md,
                f"GET /tasks/{task_id} (poll)",
                f"HTTP {rs.status_code}\n\n{_json_block(sj)}",
            )
            upstream = last_status.get("upstream_task_id")
            st = str(last_status.get("status", ""))
            if upstream or st in ("failed", "succeeded", "cancelled"):
                break
            time.sleep(2.0)

        if upstream:
            try:
                rh_snap = asyncio.run(_rh_query_once(str(upstream)))
                _append_md(
                    out_md,
                    f"RunningHub query_task({upstream})",
                    _json_block(rh_snap),
                )
            except Exception as exc:
                _append_md(
                    out_md,
                    "RunningHub query_task 异常",
                    f"```\n{exc!r}\n```\n",
                )

    print("markdown log:", out_md.resolve())
    if last_status.get("status") == "failed":
        print("task failed:", last_status.get("error_message"))
        return 2
    if not upstream:
        print("timeout: no upstream_task_id yet; see", out_md)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
