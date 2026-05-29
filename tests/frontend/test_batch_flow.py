"""Telegram batch workflow helper tests."""

import io
import zipfile
from types import SimpleNamespace

from frontend.bot.handlers import batch

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 12


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


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_batch_archive_keyboard_has_cancel_only() -> None:
    markup = batch._archive_keyboard("zh_hans")

    assert _callbacks(markup) == ["batch:cancel"]
    assert _labels(markup) == ["❌ 取消任务"]


def test_batch_confirm_defaults_to_standard_priority() -> None:
    context = SimpleNamespace(
        user_data={
            "batch_image_count": 2,
            "batch_priority": "default",
        }
    )

    markup = batch._confirm_keyboard(context, "zh_hans")

    assert _callbacks(markup) == [
        "batch:start",
        "batch:priority:lite",
        "batch:priority:default",
        "batch:priority:plus",
        "batch:cancel",
    ]
    assert "⚡ 标准 ✓" in _labels(markup)
    assert str(batch._current_hold(context)) == "0.432000"


def test_count_archive_images_preserves_folder_counting() -> None:
    content = _zip(
        {
            "a/1.png": PNG_BYTES,
            "b/2.jpg": b"\xff\xd8\xff" + b"\x00" * 12,
            "__MACOSX/ignored.png": PNG_BYTES,
            ".DS_Store": b"ignored",
        }
    )

    assert batch._count_archive_images(content, "photos.zip") == 2
