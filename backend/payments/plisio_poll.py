#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Plisio invoice 轮询入账。

无公网 callback 时由 Celery Beat 定时调用。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..database.session import async_session_maker
from ..globals import logger, settings
from ..services.payment_service import PaymentService
from .plisio import PlisioProvider


@dataclass
class PlisioPollStats:
    scanned: int = 0
    completed: int = 0
    cancelled: int = 0
    failed: int = 0
    pending: int = 0
    skipped: int = 0


async def run_plisio_payment_poll_batch() -> PlisioPollStats:
    """轮询一批 pending Plisio invoice，并按状态更新本地账本。"""
    stats = PlisioPollStats()
    if not settings.payment_poll_enabled:
        logger.debug("plisio_poll: skipped (payment_poll_enabled=false)")
        return stats
    if not settings.plisio_enabled:
        logger.debug("plisio_poll: skipped (plisio_enabled=false)")
        return stats
    if not settings.plisio_api_key:
        logger.warning("plisio_poll: skipped (PLISIO_API_KEY empty)")
        return stats

    async with async_session_maker() as session:
        svc = PaymentService(session)
        payments = await svc.get_pending_payments_by_method_keyset(
            "plisio_invoice",
            cursor=None,
            limit=max(1, int(settings.payment_poll_batch_size)),
        )

    provider = PlisioProvider()
    try:
        for payment in payments:
            stats.scanned += 1
            txn_id = payment.external_payment_id
            if not txn_id:
                stats.skipped += 1
                logger.warning(
                    "plisio_poll: pending payment missing txn_id payment_id=%s",
                    payment.payment_id,
                )
                continue

            status = await provider.query_payment_status(txn_id)
            plisio_status = (status.metadata or {}).get("plisio_status", "-")
            if status.status == "completed":
                underpaid = (
                    status.amount_paid is None
                    or status.amount_paid < payment.amount_usd
                )
                if underpaid:
                    reason = (
                        f"Plisio amount mismatch: expected={payment.amount_usd} "
                        f"paid={status.amount_paid}"
                    )
                    async with async_session_maker() as session:
                        async with session.begin():
                            svc = PaymentService(session)
                            failed = await svc.fail_payment(
                                str(payment.payment_id),
                                reason=reason,
                            )
                    if failed:
                        stats.failed += 1
                    logger.warning(
                        "plisio_poll: payment amount mismatch payment_id=%s "
                        "txn_id=%s expected=%s paid=%s plisio_status=%s",
                        payment.payment_id,
                        txn_id,
                        payment.amount_usd,
                        status.amount_paid,
                        plisio_status,
                    )
                    continue
                async with async_session_maker() as session:
                    async with session.begin():
                        svc = PaymentService(session)
                        confirmed = await svc.confirm_payment(
                            str(payment.payment_id),
                            txn_id,
                            paid_amount=status.amount_paid,
                            amount_policy="at_least",
                        )
                if confirmed:
                    stats.completed += 1
                    logger.info(
                        "plisio_poll: payment completed payment_id=%s txn_id=%s",
                        payment.payment_id,
                        txn_id,
                    )
                continue

            if status.status == "cancelled":
                async with async_session_maker() as session:
                    async with session.begin():
                        svc = PaymentService(session)
                        cancelled = await svc.cancel_payment(str(payment.payment_id))
                if cancelled:
                    stats.cancelled += 1
                    logger.info(
                        "plisio_poll: payment cancelled payment_id=%s txn_id=%s "
                        "plisio_status=%s",
                        payment.payment_id,
                        txn_id,
                        plisio_status,
                    )
                continue

            if status.status == "failed":
                async with async_session_maker() as session:
                    async with session.begin():
                        svc = PaymentService(session)
                        failed = await svc.fail_payment(
                            str(payment.payment_id),
                            reason=f"Plisio status: {plisio_status}",
                        )
                if failed:
                    stats.failed += 1
                    logger.warning(
                        "plisio_poll: payment failed payment_id=%s txn_id=%s "
                        "plisio_status=%s",
                        payment.payment_id,
                        txn_id,
                        plisio_status,
                    )
                continue

            stats.pending += 1
    finally:
        await provider.close()

    logger.info(
        "plisio_poll: tick scanned=%s completed=%s cancelled=%s failed=%s "
        "pending=%s skipped=%s",
        stats.scanned,
        stats.completed,
        stats.cancelled,
        stats.failed,
        stats.pending,
        stats.skipped,
    )
    return stats
