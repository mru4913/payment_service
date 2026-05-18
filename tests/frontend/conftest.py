import pytest

from frontend.core.i18n import _cache


@pytest.fixture(autouse=True)
def _clear_i18n_cache():
    """每个测试前清空 i18n 缓存，避免污染。"""
    _cache.clear()
    yield
    _cache.clear()
