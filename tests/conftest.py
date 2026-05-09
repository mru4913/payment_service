import pytest


@pytest.fixture(autouse=True)
def _clear_i18n_cache():
    """每个测试前清空 i18n 缓存，避免污染。"""
    from frontend.core.i18n import _cache

    _cache.clear()
    yield
    _cache.clear()
