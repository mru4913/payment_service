# -*- coding: utf-8 -*-
"""用户可见任务结果提取工具。"""

from __future__ import annotations

from typing import Any

IMAGE_OUTPUT_TYPES = {"image", "png", "jpg", "jpeg", "webp"}
IMAGE_URL_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def extract_result_image_urls(result_payload: Any) -> list[str]:
    """从内部结果负载中提取用户可见图片 URL，不暴露上游任务 ID。"""
    if not isinstance(result_payload, dict):
        return []
    query = result_payload.get("query")
    if not isinstance(query, dict):
        return []
    results = query.get("results")
    if not isinstance(results, list):
        return []

    urls: list[str] = []
    seen: set[str] = set()
    for item in results:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not url.strip():
            continue

        output_type = str(item.get("output_type") or item.get("outputType") or "")
        normalized_type = output_type.strip().lower()
        clean_url = url.strip()
        is_image_type = (
            not normalized_type
            or normalized_type in IMAGE_OUTPUT_TYPES
            or "image" in normalized_type
        )
        is_image_url = clean_url.lower().split("?", 1)[0].endswith(IMAGE_URL_SUFFIXES)
        if (not is_image_type and not is_image_url) or clean_url in seen:
            continue

        seen.add(clean_url)
        urls.append(clean_url)
    return urls
