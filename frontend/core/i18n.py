#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
国际化 (i18n) 工具

支持简体中文、繁体中文、英文三种语言。
翻译文本从 locales/<lang>/messages.json 加载。
用户语言偏好存储在 User.preferences["lang"] 中。
"""

import json
from pathlib import Path
from typing import Optional

SUPPORTED_LANGS = ("zh_hans", "zh_hant", "en")
DEFAULT_LANG = "zh_hans"

_LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"
_cache: dict[str, dict] = {}


def _load_lang(lang: str) -> dict:
    if lang in _cache:
        return _cache[lang]
    path = _LOCALES_DIR / lang / "messages.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    _cache[lang] = data
    return data


def t(key: str, lang: Optional[str] = None, **kwargs) -> str:
    """获取翻译文本。

    Args:
        key: 点分隔的翻译 key，如 "recharge.confirm"
        lang: 语言代码，默认 zh_hans
        **kwargs: 格式化参数

    Returns:
        翻译后的字符串，缺失时回退到默认语言，再缺失返回 key 本身。
    """
    lang = lang if lang in SUPPORTED_LANGS else DEFAULT_LANG
    parts = key.split(".")

    # 先查目标语言
    text = _resolve(parts, _load_lang(lang))

    # 回退到默认语言
    if text is None and lang != DEFAULT_LANG:
        text = _resolve(parts, _load_lang(DEFAULT_LANG))

    if text is None:
        return key

    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


def _resolve(parts: list[str], data: dict) -> Optional[str]:
    """沿 key 路径查找嵌套字典。"""
    current = data
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current if isinstance(current, str) else None


def get_user_lang(preferences: Optional[dict]) -> str:
    """从用户 preferences JSONB 中提取语言偏好。"""
    if preferences and isinstance(preferences.get("lang"), str):
        lang = preferences["lang"]
        if lang in SUPPORTED_LANGS:
            return lang
    return DEFAULT_LANG


def lang_display_name(lang: str) -> str:
    """返回语言的显示名称。"""
    names = {
        "zh_hans": "简体中文",
        "zh_hant": "繁體中文",
        "en": "English",
    }
    return names.get(lang, lang)
