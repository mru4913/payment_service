#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""backend/workers/slot_limiter.py — 与 Lua 语义一致的内存 ``eval`` 替身。"""

from __future__ import annotations

import pytest

from backend.config import Settings
from backend.workers import slot_limiter as lim


def _mirror_acquire(
    store: dict[str, int],
    gkey: str,
    ukey: str,
    cap_g: int,
    cap_u: int,
) -> int:
    """须与 ``_ACQUIRE_LUA`` 一致（单测替身，非生产路径）。"""
    if cap_g <= 0 and cap_u <= 0:
        return 1
    ginc = 0
    if cap_g > 0:
        v = store.get(gkey, 0) + 1
        store[gkey] = v
        ginc = 1
        if v > cap_g:
            store[gkey] = v - 1
            return 0
    if cap_u > 0:
        v = store.get(ukey, 0) + 1
        store[ukey] = v
        if v > cap_u:
            if ginc:
                store[gkey] -= 1
            store[ukey] -= 1
            return 0
    return 1


def _mirror_release(
    store: dict[str, int],
    gkey: str,
    ukey: str,
    cap_g: int,
    cap_u: int,
) -> None:
    """须与 ``_RELEASE_LUA`` 一致。"""
    if cap_u > 0:
        v = store.get(ukey, 0) - 1
        store[ukey] = 0 if v < 0 else v
    if cap_g > 0:
        v = store.get(gkey, 0) - 1
        store[gkey] = 0 if v < 0 else v


class _EvalStub:
    def __init__(self, store: dict[str, int]) -> None:
        self._store = store
        self._acquire_lua, self._release_lua = lim.slot_lua_scripts()

    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> int:
        keys = keys_and_args[:numkeys]
        args = keys_and_args[numkeys:]
        gkey, ukey = str(keys[0]), str(keys[1])
        cap_g, cap_u = int(args[0]), int(args[1])
        if script == self._acquire_lua:
            return _mirror_acquire(self._store, gkey, ukey, cap_g, cap_u)
        if script == self._release_lua:
            _mirror_release(self._store, gkey, ukey, cap_g, cap_u)
            return 1
        raise AssertionError("unexpected lua script")


@pytest.fixture(autouse=True)
async def _reset_slot_redis() -> None:
    await lim.close_slot_redis()
    yield
    await lim.close_slot_redis()


@pytest.mark.asyncio
async def test_global_cap_blocks_third(monkeypatch: pytest.MonkeyPatch) -> None:
    store: dict[str, int] = {}
    stub = _EvalStub(store)

    async def _fake_get(_url: str) -> _EvalStub:
        return stub

    monkeypatch.setattr(lim, "_get_redis", _fake_get)
    s = Settings()
    s.celery_broker_url = "redis://localhost/0"
    s.slot_max_concurrent_global = 2
    s.slot_max_concurrent_per_user = 0

    assert await lim.try_acquire_slot(s, 1) is True
    assert await lim.try_acquire_slot(s, 2) is True
    assert await lim.try_acquire_slot(s, 3) is False

    await lim.release_slot(s, 1)
    assert await lim.try_acquire_slot(s, 3) is True


@pytest.mark.asyncio
async def test_per_user_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    store: dict[str, int] = {}
    stub = _EvalStub(store)

    async def _fake_get(_url: str) -> _EvalStub:
        return stub

    monkeypatch.setattr(lim, "_get_redis", _fake_get)
    s = Settings()
    s.celery_broker_url = "redis://localhost/0"
    s.slot_max_concurrent_global = 10
    s.slot_max_concurrent_per_user = 1

    assert await lim.try_acquire_slot(s, 42) is True
    assert await lim.try_acquire_slot(s, 42) is False
    assert await lim.try_acquire_slot(s, 43) is True


@pytest.mark.asyncio
async def test_both_caps_disabled_no_redis_needed() -> None:
    s = Settings()
    s.slot_max_concurrent_global = 0
    s.slot_max_concurrent_per_user = 0
    assert await lim.try_acquire_slot(s, 1) is True


@pytest.mark.asyncio
async def test_release_never_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    store = {f"{lim.SLOT_KEY_PREFIX}global": 0}
    stub = _EvalStub(store)

    async def _fake_get(_url: str) -> _EvalStub:
        return stub

    monkeypatch.setattr(lim, "_get_redis", _fake_get)
    s = Settings()
    s.celery_broker_url = "redis://localhost/0"
    s.slot_max_concurrent_global = 2
    s.slot_max_concurrent_per_user = 0

    await lim.release_slot(s, 1)
    assert store[f"{lim.SLOT_KEY_PREFIX}global"] == 0
