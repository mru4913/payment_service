"""i18n 国际化模块单元测试"""

from unittest.mock import patch


from frontend.core.i18n import (
    t,
    get_user_lang,
    lang_display_name,
    _resolve,
    SUPPORTED_LANGS,
)


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
