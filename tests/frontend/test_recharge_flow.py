"""Recharge flow UI helpers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from frontend.bot.handlers.recharge import (
    _ACTIVE_PANEL_CHAT_ID,
    _ACTIVE_PANEL_MESSAGE_ID,
    _reply_active_panel,
)
from frontend.bot.keyboards import plisio_invoice_keyboard, recharge_amount_keyboard


def test_recharge_amount_keyboard_uses_usd_labels() -> None:
    markup = recharge_amount_keyboard("en")
    labels = [
        button.text
        for row in markup.inline_keyboard
        for button in row
    ]

    assert labels[:4] == ["$10", "$20", "$50", "$100"]
    assert labels[-1] == "↩️ Back"


def test_plisio_invoice_keyboard_has_open_url_and_status() -> None:
    markup = plisio_invoice_keyboard(
        "payment-1",
        "https://plisio.net/invoice/txn-1",
        "en",
    )

    open_button = markup.inline_keyboard[0][0]
    status_button = markup.inline_keyboard[1][0]
    assert open_button.url == "https://plisio.net/invoice/txn-1"
    assert status_button.callback_data == "recharge:status:payment-1"
    assert len(markup.inline_keyboard[1]) == 1


@pytest.mark.asyncio
async def test_reply_active_panel_retires_previous_recharge_panel() -> None:
    context = SimpleNamespace(
        user_data={
            _ACTIVE_PANEL_CHAT_ID: 10,
            _ACTIVE_PANEL_MESSAGE_ID: 20,
        },
        bot=SimpleNamespace(delete_message=AsyncMock()),
    )
    sent = SimpleNamespace(chat_id=10, message_id=21)
    msg = SimpleNamespace(reply_text=AsyncMock(return_value=sent))

    await _reply_active_panel(msg, context, "latest")

    context.bot.delete_message.assert_awaited_once_with(chat_id=10, message_id=20)
    msg.reply_text.assert_awaited_once_with("latest")
    assert context.user_data[_ACTIVE_PANEL_CHAT_ID] == 10
    assert context.user_data[_ACTIVE_PANEL_MESSAGE_ID] == 21
