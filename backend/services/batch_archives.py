#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Archive validation/extraction helpers for batch image workflows."""

from __future__ import annotations

import io
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import BinaryIO

from ..storage.local import save_upload

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_SYSTEM_NAMES = {"__MACOSX", ".DS_Store", "Thumbs.db"}


class BatchArchiveError(Exception):
    """Archive upload cannot be accepted."""

    def __init__(self, message: str, code: str = "invalid_archive") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ExtractedBatchImage:
    """One validated image extracted from an uploaded archive."""

    relative_path: str
    file_ref: str
    bytes_size: int


@dataclass(frozen=True, slots=True)
class ExtractedBatchArchive:
    """Validated archive payload ready for batch task creation."""

    source_archive_name: str
    archive_format: str
    images: list[ExtractedBatchImage]


def detect_image_content_type(content: bytes) -> str | None:
    """Lightweight JPEG/PNG/WebP magic-byte validation."""
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if (
        len(content) >= 12
        and content[:4] == b"RIFF"
        and content[8:12] == b"WEBP"
    ):
        return "image/webp"
    return None


def detect_archive_format(filename: str, content: bytes) -> str:
    """Return zip/tar/tar.gz based on filename and real archive parser support."""
    lower = filename.lower()
    stream = io.BytesIO(content)
    if lower.endswith(".zip"):
        if not zipfile.is_zipfile(stream):
            raise BatchArchiveError("上传文件不是有效 ZIP 压缩包")
        return "zip"
    if lower.endswith((".tar.gz", ".tgz")):
        try:
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz"):
                return "tar.gz"
        except tarfile.TarError as exc:
            raise BatchArchiveError("上传文件不是有效 tar.gz 压缩包") from exc
    if lower.endswith(".tar"):
        try:
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:"):
                return "tar"
        except tarfile.TarError as exc:
            raise BatchArchiveError("上传文件不是有效 tar 压缩包") from exc
    raise BatchArchiveError("仅支持 zip、tar、tar.gz 压缩包", "unsupported_archive")


def extract_batch_archive(
    *,
    content: bytes,
    filename: str,
    max_items: int,
    max_unpacked_bytes: int,
    max_image_bytes: int,
) -> ExtractedBatchArchive:
    """Validate and persist image files from a ZIP/TAR archive."""
    if not content:
        raise BatchArchiveError("上传压缩包为空", "empty_archive")
    source_name = filename or "archive"
    archive_format = detect_archive_format(source_name, content)
    images = (
        _extract_zip_images(
            content,
            max_items=max_items,
            max_unpacked_bytes=max_unpacked_bytes,
            max_image_bytes=max_image_bytes,
        )
        if archive_format == "zip"
        else _extract_tar_images(
            content,
            archive_format=archive_format,
            max_items=max_items,
            max_unpacked_bytes=max_unpacked_bytes,
            max_image_bytes=max_image_bytes,
        )
    )

    if not images:
        raise BatchArchiveError("压缩包内没有可处理的图片", "no_images")

    return ExtractedBatchArchive(
        source_archive_name=source_name,
        archive_format=archive_format,
        images=images,
    )


def cleanup_extracted_batch_archive(archive: ExtractedBatchArchive | None) -> int:
    """Remove uploaded image files when batch creation fails before commit."""
    if archive is None:
        return 0
    return _cleanup_images(archive.images)


def result_archive_name(source_archive_name: str, archive_format: str) -> str:
    """Return user-facing result archive filename."""
    name = PurePosixPath(source_archive_name).name or "batch"
    lower = name.lower()
    if archive_format == "tar.gz":
        if lower.endswith(".tar.gz"):
            stem = name[:-7]
        elif lower.endswith(".tgz"):
            stem = name[:-4]
        else:
            stem = name
        return f"{stem}_result.tar.gz"
    if archive_format in {"zip", "tar"}:
        suffix = f".{archive_format}"
        stem = name[: -len(suffix)] if lower.endswith(suffix) else name
        return f"{stem}_result.{archive_format}"
    return f"{name}_result.zip"


def result_relative_path(original_relative_path: str) -> str:
    """Keep directory and stem, normalize successful output to .png."""
    path = PurePosixPath(original_relative_path)
    return str(path.with_suffix(".png"))


def _safe_relative_path(raw_name: str) -> str | None:
    name = raw_name.replace("\\", "/").strip()
    if not name:
        raise BatchArchiveError("压缩包内存在空路径")
    path = PurePosixPath(name)
    if path.is_absolute():
        raise BatchArchiveError(f"压缩包内存在绝对路径：{raw_name}")
    parts = path.parts
    if any(part in {"", ".", ".."} for part in parts):
        raise BatchArchiveError(f"压缩包内存在不安全路径：{raw_name}")
    if any(part in _SYSTEM_NAMES or part.startswith(".") for part in parts):
        return None
    return str(path)


def _validate_member_path(
    raw_name: str,
    *,
    seen: set[str],
) -> str | None:
    safe_path = _safe_relative_path(raw_name)
    if safe_path is None:
        return None
    if safe_path in seen:
        raise BatchArchiveError(f"压缩包内存在重复路径：{safe_path}")
    seen.add(safe_path)
    return safe_path


def _record_declared_size(
    *,
    safe_path: str,
    declared_size: int,
    total_unpacked: int,
    max_unpacked_bytes: int,
) -> int:
    if declared_size < 0:
        raise BatchArchiveError(f"压缩包内文件大小无效：{safe_path}")
    total_unpacked += declared_size
    if total_unpacked > max_unpacked_bytes:
        raise BatchArchiveError("压缩包解压后总大小超过限制")
    return total_unpacked


def _validate_image_count(count: int, max_items: int) -> None:
    if count > max_items:
        raise BatchArchiveError(f"批量处理最多支持 {max_items} 张图片")


def _persist_image(
    *,
    safe_path: str,
    data: bytes,
    declared_size: int,
    max_image_bytes: int,
) -> ExtractedBatchImage:
    if declared_size <= 0:
        raise BatchArchiveError(f"图片为空：{safe_path}")
    if declared_size > max_image_bytes:
        raise BatchArchiveError(f"单张图片超过大小限制：{safe_path}")
    if len(data) != declared_size:
        raise BatchArchiveError(f"压缩包内文件大小不一致：{safe_path}")
    if detect_image_content_type(data) is None:
        raise BatchArchiveError(f"图片内容无效：{safe_path}")
    file_ref = save_upload(data, filename=PurePosixPath(safe_path).name)
    return ExtractedBatchImage(
        relative_path=safe_path,
        file_ref=file_ref,
        bytes_size=declared_size,
    )


def _cleanup_images(images: list[ExtractedBatchImage]) -> int:
    removed = 0
    for image in images:
        try:
            path = Path(image.file_ref)
            if path.is_file():
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def _read_declared_member(
    fp: BinaryIO,
    *,
    safe_path: str,
    declared_size: int,
) -> bytes:
    data = fp.read(declared_size + 1)
    if len(data) != declared_size:
        raise BatchArchiveError(f"压缩包内文件大小不一致：{safe_path}")
    return data


def _extract_zip_images(
    content: bytes,
    *,
    max_items: int,
    max_unpacked_bytes: int,
    max_image_bytes: int,
) -> list[ExtractedBatchImage]:
    images: list[ExtractedBatchImage] = []
    seen: set[str] = set()
    total_unpacked = 0
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                safe_path = _validate_member_path(info.filename, seen=seen)
                if safe_path is None:
                    continue
                total_unpacked = _record_declared_size(
                    safe_path=safe_path,
                    declared_size=int(info.file_size),
                    total_unpacked=total_unpacked,
                    max_unpacked_bytes=max_unpacked_bytes,
                )
                if PurePosixPath(safe_path).suffix.lower() not in _IMAGE_SUFFIXES:
                    continue
                _validate_image_count(len(images) + 1, max_items)
                if info.file_size > max_image_bytes:
                    raise BatchArchiveError(f"单张图片超过大小限制：{safe_path}")
                with zf.open(info) as fp:
                    data = _read_declared_member(
                        fp,
                        safe_path=safe_path,
                        declared_size=int(info.file_size),
                    )
                images.append(
                    _persist_image(
                        safe_path=safe_path,
                        data=data,
                        declared_size=int(info.file_size),
                        max_image_bytes=max_image_bytes,
                    )
                )
    except Exception:
        _cleanup_images(images)
        raise
    return images


def _extract_tar_images(
    content: bytes,
    *,
    archive_format: str,
    max_items: int,
    max_unpacked_bytes: int,
    max_image_bytes: int,
) -> list[ExtractedBatchImage]:
    images: list[ExtractedBatchImage] = []
    seen: set[str] = set()
    total_unpacked = 0
    mode = "r:gz" if archive_format == "tar.gz" else "r:"
    try:
        with tarfile.open(fileobj=io.BytesIO(content), mode=mode) as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                safe_path = _validate_member_path(member.name, seen=seen)
                if safe_path is None:
                    continue
                total_unpacked = _record_declared_size(
                    safe_path=safe_path,
                    declared_size=int(member.size),
                    total_unpacked=total_unpacked,
                    max_unpacked_bytes=max_unpacked_bytes,
                )
                if PurePosixPath(safe_path).suffix.lower() not in _IMAGE_SUFFIXES:
                    continue
                _validate_image_count(len(images) + 1, max_items)
                if member.size > max_image_bytes:
                    raise BatchArchiveError(f"单张图片超过大小限制：{safe_path}")
                fp = tf.extractfile(member)
                if fp is None:
                    continue
                data = _read_declared_member(
                    fp,
                    safe_path=safe_path,
                    declared_size=int(member.size),
                )
                images.append(
                    _persist_image(
                        safe_path=safe_path,
                        data=data,
                        declared_size=int(member.size),
                        max_image_bytes=max_image_bytes,
                    )
                )
    except Exception:
        _cleanup_images(images)
        raise
    return images
