"""Backend 薄封装：从 settings 读取配置，暴露便捷函数。"""

from __future__ import annotations

from typing import BinaryIO

from common.storage import LocalStorage, resolve_file_ref as _resolve_file_ref

from ..globals import settings

__all__ = ["resolve_file_ref", "save_upload"]

_default_storage: LocalStorage | None = None


def _get_storage() -> LocalStorage:
    global _default_storage  # noqa: PLW0603
    if _default_storage is None:
        _default_storage = LocalStorage(settings.upload_dir)
    return _default_storage


def save_upload(
    content: bytes | BinaryIO,
    *,
    filename: str | None = None,
    suffix: str = "",
) -> str:
    """保存上传文件，返回绝对路径字符串（写入 input_payload）。"""
    path = _get_storage().save(content, filename=filename, suffix=suffix)
    return str(path)


async def resolve_file_ref(ref: str) -> tuple[bytes, str, str | None]:
    """统一解析文件引用（委托给 common.storage）。"""
    return await _resolve_file_ref(ref)
