#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Plisio invoice 支付提供商。

第一版只使用 invoice + 轮询，不依赖公网 callback。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

import httpx

from ..globals import logger, settings
from .base import PaymentProvider, PaymentRequest, PaymentResult, PaymentStatus

_INVOICE_NEW_PATH = "/invoices/new"
_OPERATIONS_PATH = "/operations"
_PLISIO_IN_PROGRESS = {"new", "pending", "pending internal"}
_PLISIO_CANCELLED = {"expired", "cancelled", "cancelled duplicate"}
_PLISIO_FAILED = {"mismatch", "error"}


class PlisioProvider(PaymentProvider):
    """Plisio invoice provider."""

    def __init__(self) -> None:
        self.api_key = settings.plisio_api_key or ""
        self.base_url = settings.plisio_base_url.rstrip("/")
        self.currency = settings.plisio_recharge_currency
        self.expire_minutes = settings.plisio_invoice_expire_minutes
        self._http_client: Optional[httpx.AsyncClient] = None

    @property
    def name(self) -> str:
        return "plisio_invoice"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(15.0),
            )
        return self._http_client

    async def close(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()

    async def create_payment(self, request: PaymentRequest) -> PaymentResult:
        """创建 Plisio invoice。"""
        if not settings.plisio_enabled:
            return PaymentResult(
                success=False,
                payment_id=request.payment_id,
                error_message="Plisio 支付未启用",
            )
        if not self.api_key:
            return PaymentResult(
                success=False,
                payment_id=request.payment_id,
                error_message="Plisio API Key 未配置",
            )

        params = {
            "source_currency": "USD",
            "source_amount": str(request.amount_usd),
            "order_number": request.payment_id,
            "order_name": "Eshow recharge",
            "description": request.description or "Eshow recharge",
            "currency": self.currency,
            "allowed_psys_cids": self.currency,
            "expire_min": str(self.expire_minutes),
            "api_key": self.api_key,
        }
        if request.callback_url:
            params["callback_url"] = request.callback_url

        try:
            client = await self._get_client()
            resp = await client.get(_INVOICE_NEW_PATH, params=params)
            payload = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("plisio_create_invoice_transport_error err=%s", exc)
            return PaymentResult(
                success=False,
                payment_id=request.payment_id,
                error_message="Plisio 请求失败，请稍后重试",
            )
        except ValueError as exc:
            logger.warning("plisio_create_invoice_invalid_json err=%s", exc)
            return PaymentResult(
                success=False,
                payment_id=request.payment_id,
                error_message="Plisio 响应格式无效",
            )

        if resp.status_code >= 400 or payload.get("status") != "success":
            message = (
                _plisio_error_message(payload) or f"Plisio HTTP {resp.status_code}"
            )
            logger.warning(
                "plisio_create_invoice_failed status_code=%s message=%s",
                resp.status_code,
                message,
            )
            return PaymentResult(
                success=False,
                payment_id=request.payment_id,
                error_message=message,
                metadata={"raw": payload},
            )

        data = payload.get("data") or {}
        txn_id = str(data.get("txn_id") or "")
        invoice_url = str(data.get("invoice_url") or "")
        if not txn_id or not invoice_url:
            logger.warning("plisio_create_invoice_missing_fields data=%s", data)
            return PaymentResult(
                success=False,
                payment_id=request.payment_id,
                error_message="Plisio 响应缺少 invoice 信息",
                metadata={"raw": payload},
            )

        metadata = {
            "txn_id": txn_id,
            "invoice_url": invoice_url,
            "currency": str(
                data.get("psys_cid") or data.get("currency") or self.currency
            ),
            "source_amount_usd": str(request.amount_usd),
            "expire_minutes": self.expire_minutes,
            "raw": data,
        }
        for key in (
            "invoice_total_sum",
            "invoice_sum",
            "invoice_commission",
            "wallet_hash",
            "qr_code",
            "psys_cid",
        ):
            if data.get(key) is not None:
                metadata[key] = data[key]

        return PaymentResult(
            success=True,
            payment_id=request.payment_id,
            external_payment_id=txn_id,
            payment_url=invoice_url,
            metadata=metadata,
        )

    async def query_payment_status(self, payment_id: str) -> PaymentStatus:
        """通过 Plisio operation id 查询 invoice 状态。"""
        if not self.api_key:
            return PaymentStatus(payment_id=payment_id, status="pending")

        try:
            client = await self._get_client()
            resp = await client.get(
                f"{_OPERATIONS_PATH}/{payment_id}",
                params={"api_key": self.api_key},
            )
            payload = resp.json()
        except httpx.HTTPError as exc:
            logger.warning(
                "plisio_query_invoice_transport_error payment_id=%s err=%s",
                payment_id,
                exc,
            )
            return PaymentStatus(payment_id=payment_id, status="pending")
        except ValueError as exc:
            logger.warning(
                "plisio_query_invoice_invalid_json payment_id=%s err=%s",
                payment_id,
                exc,
            )
            return PaymentStatus(payment_id=payment_id, status="pending")

        if resp.status_code >= 400 or payload.get("status") != "success":
            logger.warning(
                "plisio_query_invoice_failed payment_id=%s status_code=%s message=%s",
                payment_id,
                resp.status_code,
                _plisio_error_message(payload),
            )
            return PaymentStatus(
                payment_id=payment_id,
                status="pending",
                metadata={"raw": payload},
            )

        data = payload.get("data") or {}
        plisio_status = str(data.get("status") or "").lower()
        local_status = _map_plisio_status(plisio_status)
        amount_paid = _decimal_or_none(
            data.get("actual_invoice_sum")
            or data.get("actual_sum")
            or data.get("invoice_total_sum")
            or data.get("amount")
        )
        external_id = str(data.get("id") or payment_id)
        return PaymentStatus(
            payment_id=payment_id,
            status=local_status,
            external_payment_id=external_id,
            amount_paid=amount_paid,
            metadata={
                "plisio_status": plisio_status,
                "raw": data,
            },
        )

    async def cancel_payment(self, payment_id: str) -> bool:
        _ = payment_id
        return True

    async def validate_callback(
        self,
        callback_data: dict[str, Any],
        *,
        raw_body: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> bool:
        _ = callback_data, raw_body, headers
        return False


def _map_plisio_status(status: str) -> str:
    if status == "completed":
        return "completed"
    if status in _PLISIO_IN_PROGRESS:
        return "pending"
    if status in _PLISIO_CANCELLED:
        return "cancelled"
    if status in _PLISIO_FAILED:
        return "failed"
    return "pending"


def _plisio_error_message(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if isinstance(data, dict):
        msg = data.get("message") or data.get("name")
        return str(msg) if msg else None
    return None


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None
