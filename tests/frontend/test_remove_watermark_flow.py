"""Telegram remove watermark flow pure helper tests."""

from decimal import Decimal
from types import SimpleNamespace

from frontend.bot.handlers import remove_watermark
from frontend.integrations import task_body_for_create


def _callbacks(markup):
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
    ]


def _labels(markup):
    return [
        button.text
        for row in markup.inline_keyboard
        for button in row
    ]


def test_remove_watermark_image_keyboard_has_next_and_cancel_only() -> None:
    markup = remove_watermark._image_keyboard("zh_hans", can_next=True)

    assert _callbacks(markup) == [
        "remove_watermark:image_next",
        "remove_watermark:cancel",
    ]
    assert _labels(markup) == [
        "➡️ 下一步：确认参数",
        "❌ 取消任务",
    ]


def test_remove_watermark_confirm_defaults_to_standard_priority() -> None:
    context = SimpleNamespace(user_data={})

    markup = remove_watermark._confirm_keyboard(context, "zh_hans")

    assert _callbacks(markup) == [
        "remove_watermark:start",
        "remove_watermark:priority:lite",
        "remove_watermark:priority:default",
        "remove_watermark:priority:plus",
        "remove_watermark:cancel",
    ]
    assert "⚡ 标准 ✓" in _labels(markup)
    assert remove_watermark._current_hold(context) == Decimal("0.216000")


def test_remove_watermark_payload_uses_image_only() -> None:
    context = SimpleNamespace(
        user_data={
            "remove_watermark_image": "file_ref://image.png",
        }
    )

    body = task_body_for_create(
        telegram_id=1,
        task_type="remove_watermark",
        third_party_platform="runninghub",
        priority_type="default",
        input_payload=remove_watermark._task_input_payload(context),
    )

    assert body["task_type"] == "remove_watermark"
    assert body["input_payload"] == {
        "image": "file_ref://image.png",
    }
    assert "prompt" not in body["input_payload"]
    assert "face_images" not in body["input_payload"]
    assert "target_image" not in body["input_payload"]
