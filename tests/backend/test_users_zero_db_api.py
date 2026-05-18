# -*- coding: utf-8 -*-
"""用户 GET preferences、PATCH、流水 total 语义。"""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

from backend.api.dependencies import (
    balance_service_read,
    user_service_read,
    user_service_write,
)
from backend.api.main import create_api_app


@pytest_asyncio.fixture
async def client_no_auth():
    with patch("backend.api.auth.settings") as s:
        s.api_key = None
        app = create_api_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            client.app = app
            yield client


def _minimal_user(**kwargs):
    base = dict(
        telegram_id=100,
        telegram_username="u",
        first_name="A",
        last_name=None,
        phone=None,
        is_premium=False,
        is_verified=False,
        is_scam=False,
        is_fake=False,
        balance=Decimal("1"),
        balance_held=Decimal("0"),
        balance_available=Decimal("1"),
        total_deposits=Decimal("0"),
        total_withdrawals=Decimal("0"),
        is_active=True,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
        display_name="A",
        preferences={"lang": "zh_hans"},
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_get_user_includes_preferences(client_no_auth):
    app = client_no_auth.app
    u = _minimal_user()

    class FakeRead:
        async def get_user(self, telegram_id: int):
            return u if telegram_id == 100 else None

    async def fake_read():
        return FakeRead()

    app.dependency_overrides[user_service_read] = fake_read
    try:
        r = await client_no_auth.get("/users/100")
        assert r.status_code == 200
        assert r.json()["preferences"] == {"lang": "zh_hans"}
    finally:
        app.dependency_overrides.pop(user_service_read, None)


@pytest.mark.asyncio
async def test_patch_user_merges_preferences(client_no_auth):
    app = client_no_auth.app
    u = _minimal_user(preferences={"lang": "zh_hans", "theme": "dark"})

    class FakeWrite:
        async def get_user(self, telegram_id: int):
            return u if telegram_id == 100 else None

        async def update_user(self, telegram_id: int, **update_data):
            for k, v in update_data.items():
                setattr(u, k, v)
            return u

    async def fake_write():
        return FakeWrite()

    app.dependency_overrides[user_service_write] = fake_write
    try:
        r = await client_no_auth.patch(
            "/users/100",
            json={"preferences": {"lang": "en"}},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["preferences"]["lang"] == "en"
        assert body["preferences"]["theme"] == "dark"
    finally:
        app.dependency_overrides.pop(user_service_write, None)


@pytest.mark.asyncio
async def test_get_user_transactions_total_is_count(client_no_auth):
    app = client_no_auth.app
    tid = uuid4()

    class FakeBal:
        async def get_user_transactions(self, telegram_id, skip=0, limit=20):
            return (
                [
                    SimpleNamespace(
                        transaction_id=tid,
                        amount_usd=Decimal("1"),
                        balance_before_usd=Decimal("0"),
                        balance_after_usd=Decimal("1"),
                        transaction_type="deposit",
                        payment_id=None,
                        task_id=None,
                        description=None,
                        created_at=datetime(2024, 1, 1, 0, 0, 0),
                    )
                ]
                if skip == 0
                else []
            )

        async def count_user_transactions(self, telegram_id):
            return 42

    async def fake_bal():
        return FakeBal()

    app.dependency_overrides[balance_service_read] = fake_bal
    try:
        r = await client_no_auth.get("/users/1/transactions", params={"limit": 1})
        assert r.status_code == 200
        assert r.json()["total"] == 42
        assert len(r.json()["transactions"]) == 1
    finally:
        app.dependency_overrides.pop(balance_service_read, None)
