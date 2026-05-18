# -*- coding: utf-8 -*-
"""用户 API 请求体（与 ORM 解耦的轻量 schema）。"""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class UserPatchBody(BaseModel):
    """PATCH /users/{telegram_id} 允许字段（其余拒绝）。"""

    model_config = ConfigDict(extra="forbid")

    preferences: Optional[dict[str, Any]] = Field(
        default=None,
        description="与已有 preferences 浅合并",
    )
    telegram_username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
