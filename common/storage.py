"""本地磁盘文件中转存储（通用模块，不依赖 backend）。

设计原则：
- 按日期子目录存储，文件名用 UUID 保证唯一
- 消费方通过绝对路径直接读取
- cleanup() 按 retain_days 删除过期日期目录
"""

from __future__ import annotations

import mimetypes
import shutil
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO


class LocalStorage:
    """本地文件存储。构造时注入 base_dir，无全局 settings 依赖。"""

    def __init__(self, base_dir: str | Path) -> None:
        self._base = Path(base_dir)

    @property
    def base_dir(self) -> Path:
        return self._base

    def _day_dir(self, day: date | None = None) -> Path:
        d = day or datetime.now(timezone.utc).date()
        return self._base / d.isoformat()

    def save(
        self,
        content: bytes | BinaryIO,
        *,
        filename: str | None = None,
        suffix: str = "",
    ) -> Path:
        """持久化文件到本地磁盘，返回绝对路径。

        Args:
            content: 文件内容（bytes 或可读 BinaryIO）。
            filename: 原始文件名（用于推断后缀）。
            suffix: 显式后缀（如 `.jpg`），优先级高于 filename 推断。
        """
        if not suffix and filename:
            suffix = Path(filename).suffix
        stem = uuid.uuid4().hex
        dest_dir = self._day_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{stem}{suffix}"

        if isinstance(content, bytes):
            dest.write_bytes(content)
        else:
            with dest.open("wb") as f:
                shutil.copyfileobj(content, f)

        return dest.resolve()

    def cleanup(self, retain_days: int = 3) -> int:
        """删除超过 retain_days 天的日期子目录，返回删除的目录数。"""
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=retain_days)
        removed = 0
        if not self._base.exists():
            return 0
        for child in self._base.iterdir():
            if not child.is_dir():
                continue
            try:
                dir_date = date.fromisoformat(child.name)
            except ValueError:
                continue
            if dir_date < cutoff:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        return removed


async def resolve_file_ref(ref: str) -> tuple[bytes, str, str | None]:
    """统一解析文件引用：本地路径或 HTTP URL。

    返回 (文件内容, 文件名, content_type)。
    """
    import httpx  # noqa: PLC0415

    path = Path(ref)
    if path.is_file():
        content = path.read_bytes()
        ct, _ = mimetypes.guess_type(path.name)
        return content, path.name, ct

    if ref.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.get(ref)
            resp.raise_for_status()
        fname = ref.rsplit("/", 1)[-1].split("?", 1)[0] or "file"
        ct = resp.headers.get("content-type")
        if not ct:
            ct, _ = mimetypes.guess_type(fname)
        return resp.content, fname, ct

    raise FileNotFoundError(f"无法解析文件引用: {ref}")
