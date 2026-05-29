#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""媒体上传 API：Bot 将 Telegram 文件中转到后端本地存储。"""

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from ...globals import logger, settings
from ...storage.local import save_upload

router = APIRouter(prefix="/media", tags=["media"])

_ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}
_READ_CHUNK_BYTES = 1024 * 1024


def _detect_image_content_type(content: bytes) -> str | None:
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


@router.post("/uploads")
async def upload_media(file: UploadFile = File(...)) -> dict[str, Any]:
    """保存一张图片，返回 Worker 可解析的 file_ref。"""
    content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    if content_type not in _ALLOWED_IMAGE_TYPES:
        logger.warning(
            "media_upload_rejected reason=unsupported_content_type filename=%s "
            "content_type=%s",
            file.filename,
            content_type or "-",
        )
        raise HTTPException(status_code=400, detail="仅支持 JPEG/PNG/WebP 图片")

    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_READ_CHUNK_BYTES):
        total += len(chunk)
        if total > settings.upload_max_bytes:
            logger.warning(
                "media_upload_rejected reason=file_too_large filename=%s "
                "content_type=%s bytes=%s max_bytes=%s",
                file.filename,
                content_type,
                total,
                settings.upload_max_bytes,
            )
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="上传图片超过大小限制",
            )
        chunks.append(chunk)
    content = b"".join(chunks)
    if not content:
        logger.warning(
            "media_upload_rejected reason=empty_file filename=%s content_type=%s",
            file.filename,
            content_type,
        )
        raise HTTPException(status_code=400, detail="上传文件为空")
    detected_type = _detect_image_content_type(content)
    if detected_type not in _ALLOWED_IMAGE_TYPES:
        logger.warning(
            "media_upload_rejected reason=invalid_image_bytes filename=%s "
            "content_type=%s bytes=%s",
            file.filename,
            content_type,
            len(content),
        )
        raise HTTPException(status_code=400, detail="上传文件不是有效图片")

    file_ref = save_upload(
        content,
        filename=file.filename,
    )
    logger.info(
        "media_upload_saved filename=%s content_type=%s bytes=%s file_ref=%s",
        file.filename,
        content_type,
        len(content),
        file_ref,
    )
    return {
        "file_ref": file_ref,
        "filename": file.filename,
        "content_type": content_type,
    }
