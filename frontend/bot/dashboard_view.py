#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Dashboard 文案渲染。"""

from decimal import Decimal

from frontend.core.utils import format_amount, tr
from frontend.integrations import BackendAPIError, get_backend_client


def _money(value: object) -> str:
    return format_amount(Decimal(str(value or "0")))


def dashboard_text(
    lang: str,
    *,
    name: str,
    created: bool,
) -> str:
    title = tr("dashboard.title", lang, name=name)
    subtitle = tr("welcome.registered", lang) if created else tr(
        "dashboard.subtitle",
        lang,
    )
    return "\n\n".join(
        [
            title,
            subtitle,
            tr("dashboard.menu_hint", lang),
            tr("dashboard.price_hint", lang),
            tr("dashboard.billing_hint", lang),
        ]
    )


def account_text(
    lang: str,
    *,
    telegram_id: int | str,
    balance: object = "0",
    available: object = "0",
    held: object = "0",
) -> str:
    return tr(
        "dashboard.account",
        lang,
        telegram_id=telegram_id or "-",
        balance=_money(balance),
        available=_money(available),
        held=_money(held),
    )


async def dashboard_text_for_user(
    lang: str,
    telegram_id: int,
    fallback_name: str | None,
) -> str:
    client = get_backend_client()
    try:
        user = await client.get_user(telegram_id)
    except BackendAPIError:
        return tr("common.error", lang)
    name = user.get("display_name") or fallback_name or str(telegram_id)
    return dashboard_text(
        lang,
        name=name,
        created=False,
    )


async def account_text_for_user(lang: str, telegram_id: int) -> str:
    client = get_backend_client()
    try:
        user = await client.get_user(telegram_id)
    except BackendAPIError:
        return tr("common.error", lang)
    return account_text(
        lang,
        telegram_id=telegram_id,
        balance=user.get("balance"),
        available=user.get("balance_available"),
        held=user.get("balance_held"),
    )
