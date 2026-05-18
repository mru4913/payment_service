#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""算力任务提交前并发槽：全局 + 每 ``telegram_id``（Redis Lua）。

用于在调用第三方「创建运行」API 前限流；与具体平台解耦。
见 ``documents/04-BUSINESS-DESIGN.md`` §7.5。``slot_max_concurrent_* <= 0`` 关闭该层；
未配置 ``slot_redis_url`` 时回退 ``celery_broker_url``；
均无且层开启时记录告警并放行 acquire。
"""

from __future__ import annotations

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from ..config import Settings
from ..globals import logger

SLOT_KEY_PREFIX = "eshow:slot:"

# KEYS[1]=global KEYS[2]=user, ARGV[1]=gcap ARGV[2]=ucap（>0 时参与计数）
_ACQUIRE_LUA = """
local gcap = tonumber(ARGV[1]) or 0
local ucap = tonumber(ARGV[2]) or 0
if gcap <= 0 and ucap <= 0 then
  return 1
end
local ginc = 0
if gcap > 0 then
  local v = redis.call('INCR', KEYS[1])
  ginc = 1
  if v > gcap then
    redis.call('DECR', KEYS[1])
    return 0
  end
end
if ucap > 0 then
  local v = redis.call('INCR', KEYS[2])
  if v > ucap then
    if ginc == 1 then
      redis.call('DECR', KEYS[1])
    end
    redis.call('DECR', KEYS[2])
    return 0
  end
end
return 1
"""

_RELEASE_LUA = """
local gcap = tonumber(ARGV[1]) or 0
local ucap = tonumber(ARGV[2]) or 0
if ucap > 0 then
  local v = redis.call('DECR', KEYS[2])
  if v < 0 then
    redis.call('SET', KEYS[2], 0)
  end
end
if gcap > 0 then
  local v = redis.call('DECR', KEYS[1])
  if v < 0 then
    redis.call('SET', KEYS[1], 0)
  end
end
return 1
"""

_redis: aioredis.Redis | None = None
_redis_url_in_use: str | None = None


def slot_lua_scripts() -> tuple[str, str]:
    """返回 (acquire_lua, release_lua)，供单测 Fake ``eval`` 与脚本对齐。"""
    return (_ACQUIRE_LUA, _RELEASE_LUA)


class SlotBusyError(Exception):
    """全局或用户槽已满；不应结算任务，由 Celery 退避重试。"""


def _effective_slot_redis_url(settings: Settings) -> str | None:
    u = (settings.slot_redis_url or "").strip()
    if u:
        return u
    b = (settings.celery_broker_url or "").strip()
    return b or None


def _global_key(prefix: str) -> str:
    return f"{prefix}global"


def _user_key(prefix: str, telegram_id: int) -> str:
    return f"{prefix}user:{telegram_id}"


async def close_slot_redis() -> None:
    """关闭进程内复用的 Redis 连接（测试或进程退出前可选调用）。"""
    global _redis, _redis_url_in_use
    if _redis is not None:
        await _redis.aclose()
        _redis = None
        _redis_url_in_use = None


async def _get_redis(url: str) -> aioredis.Redis:
    global _redis, _redis_url_in_use
    if _redis is not None and _redis_url_in_use == url:
        return _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
        _redis_url_in_use = None
    _redis = aioredis.from_url(url, decode_responses=True)
    _redis_url_in_use = url
    return _redis


async def try_acquire_slot(settings: Settings, telegram_id: int) -> bool:
    """尝试占用两层槽位；成功返回 True，已满或 Redis 错误返回 False。"""
    cap_g = settings.slot_max_concurrent_global
    cap_u = settings.slot_max_concurrent_per_user
    if cap_g <= 0 and cap_u <= 0:
        return True
    url = _effective_slot_redis_url(settings)
    if not url:
        logger.warning(
            "slot: limits enabled (global=%s per_user=%s) but no redis URL, "
            "allowing acquire",
            cap_g,
            cap_u,
        )
        return True
    gkey = _global_key(SLOT_KEY_PREFIX)
    ukey = _user_key(SLOT_KEY_PREFIX, telegram_id)
    try:
        r = await _get_redis(url)
        raw = await r.eval(_ACQUIRE_LUA, 2, gkey, ukey, str(cap_g), str(cap_u))
    except RedisError:
        # 与「槽满」一致：返回 False → Celery 退避重试。
        # Redis 短时故障不按 fail-open，避免压垮上游。
        logger.exception(
            "slot: acquire redis error telegram_id=%s",
            telegram_id,
        )
        return False
    ok = int(raw) == 1
    if not ok:
        logger.info(
            "slot: busy telegram_id=%s cap_global=%s cap_user=%s",
            telegram_id,
            cap_g,
            cap_u,
        )
    return ok


async def release_slot(settings: Settings, telegram_id: int) -> None:
    """释放一层或两层计数（与当前 cap 配置对称；双释时 DECR 钳到 0）。"""
    cap_g = settings.slot_max_concurrent_global
    cap_u = settings.slot_max_concurrent_per_user
    if cap_g <= 0 and cap_u <= 0:
        return
    url = _effective_slot_redis_url(settings)
    if not url:
        return
    gkey = _global_key(SLOT_KEY_PREFIX)
    ukey = _user_key(SLOT_KEY_PREFIX, telegram_id)
    try:
        r = await _get_redis(url)
        await r.eval(_RELEASE_LUA, 2, gkey, ukey, str(cap_g), str(cap_u))
    except RedisError:
        logger.exception(
            "slot: release redis error telegram_id=%s",
            telegram_id,
        )
