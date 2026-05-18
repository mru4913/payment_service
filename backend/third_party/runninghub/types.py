# -*- coding: utf-8 -*-
"""RunningHub 客户端入参 / 出参类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class NodeInfo:
    """对应 RH ``nodeInfoList`` 单项（camelCase 序列化时转换）。"""

    node_id: str
    field_name: str
    field_value: Any


@dataclass(frozen=True, slots=True)
class CreateTaskParams:
    """发起 ComfyUI 任务参数。"""

    workflow_id: str
    node_info_list: list[NodeInfo] = field(default_factory=list)
    instance_type: str | None = None
    webhook_url: str | None = None
    add_metadata: bool | None = None
    access_password: str | None = None
    retain_seconds: int | None = None
    use_personal_queue: bool | None = None
    workflow_json_str: str | None = None


@dataclass(frozen=True, slots=True)
class UploadResult:
    file_name: str
    download_url: str | None = None
    file_type: str | None = None
    size: str | None = None


@dataclass(frozen=True, slots=True)
class QueryOutputItem:
    url: str | None = None
    output_type: str | None = None


@dataclass(frozen=True, slots=True)
class QueryTaskResult:
    task_id: str
    status: str
    error_code: str = ""
    error_message: str = ""
    results: list[QueryOutputItem] | None = None
    client_id: str = ""
    prompt_tips: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CreateTaskResult:
    task_id: str
    task_status: str
    client_id: str = ""
    net_wss_url: str | None = None
    prompt_tips: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WebhookDetailResult:
    """``getWebhookDetail`` 成功时 ``data`` 摘要。"""

    id: str
    task_id: str
    webhook_url: str | None = None
    event_data: str | None = None
    callback_status: str | None = None
    callback_response: str | None = None
    retry_count: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)
