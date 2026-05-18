# -*- coding: utf-8 -*-
"""异步 HTTP 客户端：仅访问 FastAPI 路由。"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx

from .backend_errors import BackendAPIError, parse_error_detail
from .settings import BotBackendSettings, load_bot_backend_settings

logger = logging.getLogger(__name__)


class BackendClient:
    """带 `X-API-Key` 的 httpx 封装；不在日志中输出密钥。"""

    def __init__(self, settings: BotBackendSettings) -> None:
        self._settings = settings
        headers: dict[str, str] = {}
        if settings.api_key:
            headers["X-API-Key"] = settings.api_key
        timeout = httpx.Timeout(
            connect=settings.connect_timeout,
            read=settings.read_timeout,
            write=settings.read_timeout,
            pool=5.0,
        )
        self._client = httpx.AsyncClient(
            base_url=settings.base_url,
            headers=headers,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        try:
            resp = await self._client.request(
                method,
                path,
                json=json_body,
                params=params,
            )
        except httpx.RequestError as e:
            logger.warning("backend_http_transport_error path=%s err=%s", path, e)
            raise BackendAPIError(0, "transport", str(e)) from e

        if resp.status_code >= 400:
            body: Any
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            detail = body.get("detail") if isinstance(body, dict) else body
            code, message = parse_error_detail(detail)
            logger.warning(
                "backend_http_error path=%s status=%s code=%s",
                path,
                resp.status_code,
                code,
            )
            raise BackendAPIError(resp.status_code, code, message, raw_detail=detail)

        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    async def get_user(self, telegram_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/users/{telegram_id}")

    async def patch_user(
        self, telegram_id: int, body: dict[str, Any]
    ) -> dict[str, Any]:
        """PATCH /users/{telegram_id}（preferences 浅合并在后端完成）。"""
        return await self._request("PATCH", f"/users/{telegram_id}", json_body=body)

    async def ensure_user(
        self,
        telegram_id: int,
        *,
        telegram_username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        phone: str | None = None,
        is_premium: bool = False,
        is_verified: bool = False,
        is_scam: bool = False,
        is_fake: bool = False,
    ) -> dict[str, Any]:
        """POST /users/{telegram_id}：不存在则创建。"""
        params: dict[str, Any] = {}
        if telegram_username is not None:
            params["telegram_username"] = telegram_username
        if first_name is not None:
            params["first_name"] = first_name
        if last_name is not None:
            params["last_name"] = last_name
        if phone is not None:
            params["phone"] = phone
        params["is_premium"] = is_premium
        params["is_verified"] = is_verified
        params["is_scam"] = is_scam
        params["is_fake"] = is_fake
        return await self._request("POST", f"/users/{telegram_id}", params=params)

    async def get_user_balance(self, telegram_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/users/{telegram_id}/balance")

    async def list_user_transactions(
        self,
        telegram_id: int,
        *,
        skip: int = 0,
        limit: int = 20,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/users/{telegram_id}/transactions",
            params={"skip": skip, "limit": limit},
        )

    async def list_pending_payments(
        self,
        *,
        telegram_id: int | None = None,
        skip: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        """GET /payments/pending；含 payments、total（全量）、returned。"""
        params: dict[str, Any] = {"skip": skip, "limit": limit}
        if telegram_id is not None:
            params["telegram_id"] = telegram_id
        return await self._request("GET", "/payments/pending", params=params)

    async def create_trc20_recharge_payment(
        self,
        telegram_id: int,
        amount_usd: Decimal,
        description: str = "",
    ) -> dict[str, Any]:
        """POST /payments，``trc20_usdt`` 分支由服务端分配唯一金额。"""
        return await self._request(
            "POST",
            "/payments",
            params={
                "telegram_id": telegram_id,
                "amount_usd": str(amount_usd),
                "payment_method": "trc20_usdt",
                "description": description,
            },
        )

    async def get_payment(self, payment_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/payments/{payment_id}")

    async def cancel_payment(self, payment_id: str) -> dict[str, Any]:
        return await self._request("PUT", f"/payments/{payment_id}/cancel")

    async def get_task(self, task_id: UUID, telegram_id: int) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/tasks/{task_id}",
            params={"telegram_id": telegram_id},
        )

    async def create_task(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST /tasks；body 中 Decimal 等须已转为 JSON 可序列化类型。"""
        return await self._request("POST", "/tasks", json_body=body)


_client: BackendClient | None = None


def get_backend_client() -> BackendClient:
    """进程内懒单例。"""
    global _client
    if _client is None:
        _client = BackendClient(load_bot_backend_settings())
    return _client


async def reset_backend_client() -> None:
    """关闭并丢弃单例（例如 Bot shutdown）。"""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def task_body_for_create(
    *,
    telegram_id: int,
    task_type: str,
    third_party_platform: str,
    priority_type: str,
    input_payload: dict[str, Any],
    hold_amount: Decimal,
    task_description: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """构造 POST /tasks JSON（与 CreateTaskRequest 对齐）。"""
    body: dict[str, Any] = {
        "telegram_id": telegram_id,
        "task_type": task_type,
        "third_party_platform": third_party_platform,
        "priority_type": priority_type,
        "input_payload": input_payload,
        "hold_amount": str(hold_amount),
    }
    if task_description is not None:
        body["task_description"] = task_description
    if idempotency_key is not None:
        body["idempotency_key"] = idempotency_key
    return body
