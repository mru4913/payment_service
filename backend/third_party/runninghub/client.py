# -*- coding: utf-8 -*-
"""RunningHub OpenAPI：上传、创建任务、查询、工作流 JSON、Webhook 运维。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any, BinaryIO
from urllib.parse import urlparse

import httpx

from backend.third_party.runninghub.constants import (
    DEFAULT_BASE_URL,
    DEFAULT_HOST_HEADER,
    PATH_CREATE_COMFY_TASK,
    PATH_GET_JSON_API_FORMAT,
    PATH_GET_WEBHOOK_DETAIL,
    PATH_QUERY_TASK_V2,
    PATH_RETRY_WEBHOOK,
    PATH_UPLOAD_BINARY,
)
from backend.third_party.runninghub.errors import MISSING_API_KEY, RunningHubAPIError
from backend.third_party.runninghub.types import (
    CreateTaskParams,
    CreateTaskResult,
    NodeInfo,
    QueryOutputItem,
    QueryTaskResult,
    UploadResult,
    WebhookDetailResult,
)

_DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_MAX_RETRIES = 3
_BACKOFF_BASE_S = 0.35


def _looks_like_rh_envelope(obj: dict[str, Any]) -> bool:
    """避免扁平 JSON 中偶然出现 ``code`` 字段时误判为信封。"""
    if "code" not in obj:
        return False
    c = obj.get("code")
    if not isinstance(c, int):
        return False
    return "data" in obj or "msg" in obj or "message" in obj


def _unwrap_envelope_or_flat(obj: Any) -> dict[str, Any]:
    """解析 ``{code,msg,data}`` 信封；否则视为扁平负载。"""
    if not isinstance(obj, dict):
        msg = "RunningHub response JSON must be an object"
        raise RunningHubAPIError(msg, body=obj)
    if not _looks_like_rh_envelope(obj):
        return obj
    code = obj["code"]
    if code != 0:
        rh_msg = str(obj.get("msg") or obj.get("message") or "api error")
        raise RunningHubAPIError(
            f"RunningHub API error: {rh_msg}",
            rh_code=code,
            rh_msg=rh_msg,
            body=obj,
        )
    data = obj.get("data")
    if data is None:
        return {}
    if isinstance(data, dict):
        return data
    msg = "RunningHub envelope: success but data is not a JSON object"
    raise RunningHubAPIError(msg, body=obj)


def _query_inner_payload(obj: Any) -> dict[str, Any]:
    """``query``：兼容信封与扁平两种顶层 JSON。"""
    if not isinstance(obj, dict):
        msg = "RunningHub query response must be an object"
        raise RunningHubAPIError(msg, body=obj)
    if _looks_like_rh_envelope(obj):
        return _unwrap_envelope_or_flat(obj)
    return obj


def _host_header_for_base_url(base_url: str) -> str:
    try:
        host = urlparse(base_url).hostname
    except ValueError:
        return DEFAULT_HOST_HEADER
    return host if host else DEFAULT_HOST_HEADER


def _node_info_to_rh_dict(n: NodeInfo) -> dict[str, Any]:
    return {
        "nodeId": n.node_id,
        "fieldName": n.field_name,
        "fieldValue": n.field_value,
    }


class RunningHubClient:
    """纯 HTTP 客户端；无数据库与 Celery。"""

    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: httpx.Timeout | None = None,
        max_retries: int = _MAX_RETRIES,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """构造客户端。

        ``api_key`` 可为 ``None``（仅测试或延迟配置）；首次调用需鉴权的接口时
        抛出 ``RunningHubAPIError``（``rh_code == MISSING_API_KEY``）。

        若传入 ``client``，则由调用方负责在进程退出前 ``aclose()``；
        本实例仅在自建 ``AsyncClient`` 时（``client is None``）在 ``aclose()`` /
        ``async with`` 中关闭底层连接。
        """
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._host_header = _host_header_for_base_url(self._base_url)
        self._timeout = timeout or _DEFAULT_TIMEOUT
        self._max_retries = max(0, max_retries)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=self._timeout)

    def _require_api_key(self) -> str:
        if not self._api_key:
            msg = "RunningHubClient requires a non-empty api_key"
            raise RunningHubAPIError(msg, rh_code=MISSING_API_KEY)
        return self._api_key

    def _auth_headers(self) -> dict[str, str]:
        key = self._require_api_key()
        return {
            "Authorization": f"Bearer {key}",
            "Host": self._host_header,
        }

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    @staticmethod
    def _http_retryable(status: int) -> bool:
        return status == 408 or status == 429 or status >= 500

    async def _sleep_backoff(self, attempt: int) -> None:
        await asyncio.sleep(_BACKOFF_BASE_S * (2**attempt))

    async def _post_multipart_no_retry(
        self,
        path: str,
        *,
        files: dict[str, Any],
    ) -> dict[str, Any]:
        url = self._url(path)
        try:
            resp = await self._client.post(
                url,
                headers=self._auth_headers(),
                files=files,
            )
        except httpx.RequestError as e:
            msg = f"RunningHub request failed: {e}"
            raise RunningHubAPIError(msg, http_status=None, body=None) from e
        return await self._parse_http_json_response(resp)

    async def _post_json_with_retry(self, path: str, body: Mapping[str, Any]) -> Any:
        url = self._url(path)
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.post(
                    url,
                    headers=self._auth_headers(),
                    json=dict(body),
                )
            except httpx.RequestError as e:
                if attempt >= self._max_retries:
                    msg = f"RunningHub request failed: {e}"
                    raise RunningHubAPIError(msg, http_status=None, body=None) from e
                await self._sleep_backoff(attempt)
                continue
            if self._http_retryable(resp.status_code) and attempt < self._max_retries:
                await self._sleep_backoff(attempt)
                continue
            return await self._parse_http_json_response(resp)

    async def _parse_http_json_response(self, resp: httpx.Response) -> Any:
        if resp.status_code >= 400:
            body: Any
            try:
                body = resp.json()
            except json.JSONDecodeError:
                body = resp.text
            msg = f"HTTP {resp.status_code}"
            raise RunningHubAPIError(
                msg,
                http_status=resp.status_code,
                body=body,
            )
        try:
            return resp.json()
        except json.JSONDecodeError as e:
            raise RunningHubAPIError(
                "invalid JSON in RunningHub response",
                http_status=resp.status_code,
                body=resp.text,
            ) from e

    async def upload_media(
        self,
        *,
        file: bytes | BinaryIO,
        filename: str,
        content_type: str | None,
    ) -> UploadResult:
        """``POST /openapi/v2/media/upload/binary``（不做自动重试，避免重复上传）。"""
        ct = content_type or "application/octet-stream"
        files = {"file": (filename, file, ct)}
        raw = await self._post_multipart_no_retry(PATH_UPLOAD_BINARY, files=files)
        data = _unwrap_envelope_or_flat(raw)
        file_name = data.get("fileName") or data.get("file_name")
        if not file_name:
            msg = "upload response missing data.fileName"
            raise RunningHubAPIError(msg, body=raw)
        dl = data.get("download_url") or data.get("downloadUrl")
        ft = data.get("file_type") or data.get("fileType")
        sz = data.get("size")
        return UploadResult(
            file_name=str(file_name),
            download_url=str(dl) if dl else None,
            file_type=str(ft) if ft else None,
            size=str(sz) if sz is not None else None,
        )

    async def create_comfy_task(self, params: CreateTaskParams) -> CreateTaskResult:
        """``POST /task/openapi/create``。"""
        key = self._require_api_key()
        body: dict[str, Any] = {
            "apiKey": key,
            "workflowId": params.workflow_id,
            "nodeInfoList": [_node_info_to_rh_dict(n) for n in params.node_info_list],
        }
        if params.instance_type is not None and str(params.instance_type).strip() != "":
            body["instanceType"] = params.instance_type
        if params.webhook_url is not None:
            body["webhookUrl"] = params.webhook_url
        if params.add_metadata is not None:
            body["addMetadata"] = params.add_metadata
        if params.access_password is not None:
            body["accessPassword"] = params.access_password
        if params.retain_seconds is not None:
            body["retainSeconds"] = params.retain_seconds
        if params.use_personal_queue is not None:
            body["usePersonalQueue"] = params.use_personal_queue
        if params.workflow_json_str is not None:
            body["workflowJson"] = params.workflow_json_str
        raw = await self._post_json_with_retry(PATH_CREATE_COMFY_TASK, body)
        data = _unwrap_envelope_or_flat(raw)
        task_id = data.get("taskId") or data.get("task_id")
        if not task_id:
            msg = "create response missing data.taskId"
            raise RunningHubAPIError(msg, body=raw)
        status = str(data.get("taskStatus") or data.get("task_status") or "")
        wss = data.get("netWssUrl") or data.get("net_wss_url")
        return CreateTaskResult(
            task_id=str(task_id),
            task_status=status,
            client_id=str(data.get("clientId") or data.get("client_id") or ""),
            net_wss_url=str(wss) if wss else None,
            prompt_tips=str(data.get("promptTips") or data.get("prompt_tips") or ""),
            raw=data if isinstance(data, dict) else {},
        )

    async def query_task(self, task_id: str) -> QueryTaskResult:
        """``POST /openapi/v2/query``；兼容信封与扁平 JSON。"""
        key = self._require_api_key()
        body = {"apiKey": key, "taskId": task_id}
        raw = await self._post_json_with_retry(PATH_QUERY_TASK_V2, body)
        inner = _query_inner_payload(raw)
        tid = inner.get("taskId") or inner.get("task_id") or task_id
        status = str(inner.get("status") or "")
        err_c = str(inner.get("errorCode") or inner.get("error_code") or "")
        err_m = str(inner.get("errorMessage") or inner.get("error_message") or "")
        results_raw = inner.get("results")
        out_list: list[QueryOutputItem] | None = None
        if "results" in inner and isinstance(results_raw, list):
            out_list = []
            for item in results_raw:
                if isinstance(item, dict):
                    ot = item.get("outputType") or item.get("output_type")
                    u = item.get("url")
                    out_list.append(
                        QueryOutputItem(
                            url=str(u) if u else None,
                            output_type=str(ot) if ot else None,
                        )
                    )
        return QueryTaskResult(
            task_id=str(tid),
            status=status,
            error_code=err_c,
            error_message=err_m,
            results=out_list,
            client_id=str(inner.get("clientId") or inner.get("client_id") or ""),
            prompt_tips=str(inner.get("promptTips") or inner.get("prompt_tips") or ""),
            raw=dict(inner) if isinstance(inner, dict) else {},
        )

    async def get_workflow_json(self, workflow_id: str) -> str:
        """``POST /api/openapi/getJsonApiFormat``。

        返回 ``data.prompt`` 原始字符串（常为 JSON 字符串）；由调用方 ``json.loads``。
        """
        key = self._require_api_key()
        body = {"apiKey": key, "workflowId": workflow_id}
        raw = await self._post_json_with_retry(PATH_GET_JSON_API_FORMAT, body)
        data = _unwrap_envelope_or_flat(raw)
        prompt = data.get("prompt")
        if not isinstance(prompt, str):
            msg = "getJsonApiFormat: data.prompt must be a string"
            raise RunningHubAPIError(msg, body=raw)
        return prompt

    async def get_webhook_detail(self, task_id: str) -> WebhookDetailResult:
        """``POST /task/openapi/getWebhookDetail``。"""
        key = self._require_api_key()
        body = {"apiKey": key, "taskId": task_id}
        raw = await self._post_json_with_retry(PATH_GET_WEBHOOK_DETAIL, body)
        data = _unwrap_envelope_or_flat(raw)
        wid = data.get("id")
        if wid is None:
            msg = "getWebhookDetail: data.id missing"
            raise RunningHubAPIError(msg, body=raw)
        rh_task = data.get("taskId") or data.get("task_id")
        rc = data.get("retryCount") if "retryCount" in data else data.get("retry_count")
        retry_count: int | None
        if rc is None:
            retry_count = None
        else:
            try:
                retry_count = int(rc)
            except (TypeError, ValueError):
                retry_count = None
        wurl = data.get("webhookUrl") or data.get("webhook_url")
        ev = data.get("eventData") or data.get("event_data")
        return WebhookDetailResult(
            id=str(wid),
            task_id=str(rh_task or task_id),
            webhook_url=str(wurl) if wurl else None,
            event_data=str(ev) if ev else None,
            callback_status=(
                str(cs)
                if (cs := data.get("callbackStatus") or data.get("callback_status"))
                else None
            ),
            callback_response=(
                str(cr)
                if (cr := data.get("callbackResponse") or data.get("callback_response"))
                else None
            ),
            retry_count=retry_count,
            raw=dict(data) if isinstance(data, dict) else {},
        )

    async def retry_webhook(self, webhook_id: str, webhook_url: str) -> None:
        """``POST /task/openapi/retryWebhook``；成功时 ``code == 0``。"""
        key = self._require_api_key()
        body = {
            "apiKey": key,
            "webhookId": webhook_id,
            "webhookUrl": webhook_url,
        }
        raw = await self._post_json_with_retry(PATH_RETRY_WEBHOOK, body)
        _unwrap_envelope_or_flat(raw)

    async def aclose(self) -> None:
        """关闭自建的 ``httpx.AsyncClient``；注入的 ``client`` 不会被关闭。"""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> RunningHubClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()
