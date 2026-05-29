"""i18n 国际化模块单元测试"""

import json
import re
from pathlib import Path
from unittest.mock import patch


from frontend.core.i18n import (
    t,
    get_user_lang,
    lang_display_name,
    _resolve,
    SUPPORTED_LANGS,
)

LOCALES_DIR = Path(__file__).resolve().parents[2] / "frontend" / "locales"
PLACEHOLDER_RE = re.compile(r"(?<!{){([a-zA-Z_][a-zA-Z0-9_]*)}(?!})")


def _flatten_locale(data: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten_locale(value, path))
        else:
            out[path] = str(value)
    return out


class TestResolve:
    def test_simple_key(self):
        assert _resolve(["hello"], {"hello": "world"}) == "world"

    def test_nested_key(self):
        data = {"a": {"b": {"c": "deep"}}}
        assert _resolve(["a", "b", "c"], data) == "deep"

    def test_missing_key(self):
        assert _resolve(["missing"], {"hello": "world"}) is None

    def test_non_string_leaf(self):
        assert _resolve(["a"], {"a": {"nested": "obj"}}) is None

    def test_empty_parts(self):
        assert _resolve([], {"a": "b"}) is None


class TestT:
    def test_returns_key_when_missing(self):
        with patch("frontend.core.i18n._load_lang", return_value={}):
            assert t("nonexistent.key") == "nonexistent.key"

    def test_returns_translation(self):
        data = {"common": {"confirm": "确认"}}
        with patch("frontend.core.i18n._load_lang", return_value=data):
            assert t("common.confirm", lang="zh_hans") == "确认"

    def test_format_kwargs(self):
        data = {"msg": "Hello {name}"}
        with patch("frontend.core.i18n._load_lang", return_value=data):
            assert t("msg", name="World") == "Hello World"

    def test_language_changed_placeholder_does_not_conflict_with_locale(self):
        assert (
            t("language.changed", lang="zh_hans", language="简体中文")
            == "✅ 语言已切换为：简体中文"
        )

    def test_format_missing_kwarg_returns_raw(self):
        data = {"msg": "Hello {name}"}
        with patch("frontend.core.i18n._load_lang", return_value=data):
            assert t("msg") == "Hello {name}"

    def test_fallback_to_default_lang(self):
        def fake_load(lang):
            if lang == "en":
                return {}
            return {"greeting": "你好"}

        with patch("frontend.core.i18n._load_lang", side_effect=fake_load):
            result = t("greeting", lang="en")
            assert result == "你好"

    def test_unsupported_lang_uses_default(self):
        data = {"key": "value"}
        with patch("frontend.core.i18n._load_lang", return_value=data):
            result = t("key", lang="fr")
            assert result == "value"


class TestGetUserLang:
    def test_valid_lang(self):
        assert get_user_lang({"lang": "en"}) == "en"

    def test_none_preferences(self):
        assert get_user_lang(None) == "zh_hans"

    def test_empty_preferences(self):
        assert get_user_lang({}) == "zh_hans"

    def test_invalid_lang(self):
        assert get_user_lang({"lang": "fr"}) == "zh_hans"

    def test_non_string_lang(self):
        assert get_user_lang({"lang": 123}) == "zh_hans"

    def test_all_supported_langs(self):
        for lang in SUPPORTED_LANGS:
            assert get_user_lang({"lang": lang}) == lang


class TestLangDisplayName:
    def test_known_langs(self):
        assert lang_display_name("zh_hans") == "简体中文"
        assert lang_display_name("zh_hant") == "繁體中文"
        assert lang_display_name("en") == "English"

    def test_unknown_lang(self):
        assert lang_display_name("fr") == "fr"


def test_locale_files_have_matching_keys_and_placeholders():
    """All supported locale JSON files should expose the same message contract."""
    flattened: dict[str, dict[str, str]] = {}
    for lang in SUPPORTED_LANGS:
        path = LOCALES_DIR / lang / "messages.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        flattened[lang] = _flatten_locale(data)

    reference_lang = SUPPORTED_LANGS[0]
    reference_keys = set(flattened[reference_lang])
    for lang in SUPPORTED_LANGS[1:]:
        assert set(flattened[lang]) == reference_keys

    for key in sorted(reference_keys):
        reference_placeholders = set(
            PLACEHOLDER_RE.findall(flattened[reference_lang][key])
        )
        for lang in SUPPORTED_LANGS[1:]:
            assert set(PLACEHOLDER_RE.findall(flattened[lang][key])) == (
                reference_placeholders
            )
