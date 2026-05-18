# -*- coding: utf-8 -*-
"""从应用配置构造 ``RunningHubClient``。"""

from __future__ import annotations

from backend.config import Settings

from .client import RunningHubClient
from .errors import MISSING_API_KEY, RunningHubAPIError


def get_runninghub_client(settings: Settings) -> RunningHubClient:
    """使用 ``Settings`` 中的 RunningHub 字段构造客户端。

    ``runninghub_api_key`` 为空时抛出 ``RunningHubAPIError``
    （``rh_code == MISSING_API_KEY``），与其它 RH 相关失败一致。
    """
    if not settings.runninghub_api_key:
        msg = (
            "runninghub_api_key is not set; configure RUNNINGHUB_API_KEY "
            "or skip RH calls."
        )
        raise RunningHubAPIError(msg, rh_code=MISSING_API_KEY)
    return RunningHubClient(
        api_key=settings.runninghub_api_key,
        base_url=settings.runninghub_base_url,
    )
