# -*- coding: utf-8 -*-
"""Telegram compute flow 的纯函数/轻量 UI 单元测试。"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from telegram.error import TimedOut

import frontend.bot.handlers.compute.create_flow as create_flow
import frontend.bot.handlers.compute.task_status as task_status
from frontend.bot.handlers.compute.create_flow import (
    _ACTIVE_PANEL_CHAT_ID,
    _ACTIVE_PANEL_MESSAGE_ID,
    _confirm_keyboard,
    _current_hold,
    _faces_keyboard,
    _is_from_face_media_group,
    _image_attachment,
    _reply_active_panel,
    _remember_face_media_group,
    _task_card_keyboard,
    _target_keyboard,
    compute_global_callback,
)
from frontend.bot.handlers.compute.task_status import (
    render_task_status,
    result_image_urls,
    send_task_result_images,
    task_command,
)


def test_current_hold_defaults_to_standard() -> None:
    context = SimpleNamespace(user_data={})

    assert _current_hold(context) == Decimal("0.180000")


def test_current_hold_uses_selected_priority() -> None:
    context = SimpleNamespace(user_data={"compute_priority": "plus"})

    assert _current_hold(context) == Decimal("0.350000")


def test_task_card_has_status_and_restart_buttons() -> None:
    markup = _task_card_keyboard("task-1", "zh_hans")
    callbacks = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
    ]

    assert callbacks == [
        "compute:status:task-1",
        "compute:restart",
        "dashboard:home",
    ]


def test_compute_workflow_keyboards_do_not_expose_back_buttons() -> None:
    context = SimpleNamespace(user_data={})
    markups = [
        _faces_keyboard("zh_hans", can_next=True),
        _target_keyboard("zh_hans"),
        _confirm_keyboard(context, "zh_hans"),
    ]

    callbacks = [
        button.callback_data
        for markup in markups
        for row in markup.inline_keyboard
        for button in row
    ]

    assert "compute:home" not in callbacks
    assert "compute:back_faces" not in callbacks
    assert "compute:target_reset" not in callbacks


def test_image_attachment_accepts_photo() -> None:
    update = SimpleNamespace(
        effective_message=SimpleNamespace(
            photo=[
                SimpleNamespace(file_id="small", file_unique_id="small_u"),
                SimpleNamespace(file_id="big", file_unique_id="big_u"),
            ],
            document=None,
        )
    )

    assert _image_attachment(update) == ("big", "big_u.jpg", "image/jpeg")


def test_render_task_status_uses_public_code() -> None:
    text = render_task_status(
        {
            "task_id": "791cc7ee-5b79-4a51-8185-bd2c8ea1524e",
            "task_code": "791CC7EE",
            "status": "running",
            "queued_at": None,
            "started_at": None,
            "completed_at": None,
        },
        "zh_hans",
    )

    assert "任务编号：<code>791CC7EE</code>" in text


def test_result_image_urls_are_deduplicated() -> None:
    assert result_image_urls(
        {
            "result_images": [
                " https://cdn.example/a.png ",
                "https://cdn.example/a.png",
                "",
                None,
                "https://cdn.example/b.png",
            ]
        }
    ) == ["https://cdn.example/a.png", "https://cdn.example/b.png"]


def test_image_attachment_accepts_image_document() -> None:
    update = SimpleNamespace(
        effective_message=SimpleNamespace(
            photo=[],
            document=SimpleNamespace(
                file_id="doc",
                file_unique_id="doc_u",
                file_name="face.webp",
                mime_type="image/webp",
            ),
        )
    )

    assert _image_attachment(update) == ("doc", "face.webp", "image/webp")


def test_face_media_group_ids_are_remembered() -> None:
    context = SimpleNamespace(user_data={})
    update = SimpleNamespace(
        effective_message=SimpleNamespace(media_group_id="album-1"),
    )

    _remember_face_media_group(update, context)

    assert _is_from_face_media_group(update, context) is True


@pytest.mark.asyncio
async def test_reply_active_panel_retires_previous_panel() -> None:
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


@pytest.mark.asyncio
async def test_status_callback_fetches_latest_task(monkeypatch) -> None:
    task_id = UUID("00000000-0000-4000-8000-000000000001")

    class _Client:
        def __init__(self) -> None:
            self.get_task = AsyncMock(
                return_value={
                    "task_id": str(task_id),
                    "task_code": "00000000",
                    "status": "running",
                    "queued_at": None,
                    "started_at": None,
                    "completed_at": None,
                    "result_images": [],
                }
            )

    client = _Client()
    monkeypatch.setattr(create_flow, "get_backend_client", lambda: client)
    monkeypatch.setattr(
        create_flow,
        "get_user_lang_from_update",
        AsyncMock(return_value="zh_hans"),
    )
    query = SimpleNamespace(
        data=f"compute:status:{task_id}",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=SimpleNamespace(reply_photo=AsyncMock(), reply_text=AsyncMock()),
    )
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=123),
    )

    await compute_global_callback(update, SimpleNamespace(user_data={}))

    client.get_task.assert_awaited_once_with(task_id, 123)
    text = query.edit_message_text.call_args.args[0]
    assert "状态：<b>running</b>" in text


@pytest.mark.asyncio
async def test_status_callback_sends_result_image_once(monkeypatch) -> None:
    task_id = UUID("00000000-0000-4000-8000-000000000001")

    class _Client:
        def __init__(self) -> None:
            self.get_task = AsyncMock(
                return_value={
                    "task_id": str(task_id),
                    "task_code": "00000000",
                    "status": "succeeded",
                    "queued_at": None,
                    "started_at": None,
                    "completed_at": None,
                    "result_images": ["https://cdn.example/result.png"],
                }
            )

    client = _Client()
    monkeypatch.setattr(create_flow, "get_backend_client", lambda: client)
    monkeypatch.setattr(
        create_flow,
        "get_user_lang_from_update",
        AsyncMock(return_value="zh_hans"),
    )
    message = SimpleNamespace(reply_photo=AsyncMock(), reply_text=AsyncMock())
    query = SimpleNamespace(
        data=f"compute:status:{task_id}",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=message,
    )
    context = SimpleNamespace(user_data={})
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=123),
    )

    await compute_global_callback(update, context)
    await compute_global_callback(update, context)

    message.reply_photo.assert_awaited_once()
    assert context.user_data["compute_result_sent_tasks"] == {str(task_id)}


@pytest.mark.asyncio
async def test_send_task_result_images_falls_back_to_text() -> None:
    msg = SimpleNamespace(
        reply_photo=AsyncMock(side_effect=RuntimeError("bad url")),
        reply_text=AsyncMock(),
    )

    sent = await send_task_result_images(
        msg,
        {
            "task_code": "41B53CFE",
            "status": "succeeded",
            "result_images": ["https://cdn.example/result.png"],
        },
        "zh_hans",
    )

    assert sent is True
    msg.reply_text.assert_awaited_once()
    assert msg.reply_text.await_args.kwargs["disable_web_page_preview"] is True


@pytest.mark.asyncio
async def test_send_task_result_images_does_not_fallback_on_timeout() -> None:
    msg = SimpleNamespace(
        reply_photo=AsyncMock(side_effect=TimedOut("slow telegram")),
        reply_text=AsyncMock(),
    )

    sent = await send_task_result_images(
        msg,
        {
            "task_code": "41B53CFE",
            "status": "succeeded",
            "result_images": ["https://cdn.example/result.png"],
        },
        "zh_hans",
    )

    assert sent is True
    msg.reply_photo.assert_awaited_once()
    msg.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_command_without_args_shows_task_history(monkeypatch) -> None:
    history = AsyncMock()
    monkeypatch.setattr(task_status, "task_history_handler", history)
    msg = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_message=msg,
        effective_user=SimpleNamespace(id=123),
    )
    context = SimpleNamespace(args=[])

    await task_command(update, context)

    history.assert_awaited_once_with(update, context)
    msg.reply_text.assert_not_awaited()
