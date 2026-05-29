"""Worker Telegram result notification."""

from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from backend.config import Settings
from backend.workers.telegram_notify import (
    send_batch_result_archives_to_user,
    send_task_failed_message_to_user,
    send_task_success_images_to_user,
)


class _Response:
    def __init__(self, *, ok: bool = True) -> None:
        self._ok = ok

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"ok": self._ok}


class _FakeTelegramClient:
    def __init__(
        self,
        *,
        fail_photo: bool = False,
        timeout_photo: bool = False,
    ) -> None:
        self.fail_photo = fail_photo
        self.timeout_photo = timeout_photo
        self.posts: list[tuple[str, dict]] = []

    async def post(self, url: str, *, json: dict):
        self.posts.append((url, json))
        if self.timeout_photo and url.endswith("/sendPhoto"):
            raise httpx.TimeoutException("maybe delivered")
        if self.fail_photo and url.endswith("/sendPhoto"):
            raise httpx.HTTPError("photo rejected")
        return _Response()


class _FakeMultipartTelegramClient:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict, dict]] = []

    async def post(self, url: str, *, data: dict, files: dict):
        self.posts.append((url, data, files))
        return _Response()


def _settings() -> Settings:
    return Settings(telegram_bot_token="token")


@pytest.mark.asyncio
async def test_send_task_success_images_to_user_sends_photo() -> None:
    client = _FakeTelegramClient()
    task_id = UUID("41b53cfe-b3ed-4bc2-96e7-c32b11439f0c")

    sent = await send_task_success_images_to_user(
        settings=_settings(),
        telegram_id=8630043577,
        task_id=task_id,
        result_payload={
            "query": {
                "results": [
                    {"url": "https://cdn.example/result.png", "output_type": "png"}
                ]
            }
        },
        client=client,  # type: ignore[arg-type]
    )

    assert sent is True
    assert client.posts[0][0].endswith("/sendPhoto")
    assert client.posts[0][1]["chat_id"] == 8630043577
    assert client.posts[0][1]["photo"] == "https://cdn.example/result.png"
    assert "41B53CFE" in client.posts[0][1]["caption"]


@pytest.mark.asyncio
async def test_send_task_success_images_to_user_falls_back_to_link() -> None:
    client = _FakeTelegramClient(fail_photo=True)

    sent = await send_task_success_images_to_user(
        settings=_settings(),
        telegram_id=1,
        task_id=UUID("41b53cfe-b3ed-4bc2-96e7-c32b11439f0c"),
        result_payload={
            "query": {
                "results": [
                    {"url": "https://cdn.example/result.png", "output_type": "png"}
                ]
            }
        },
        client=client,  # type: ignore[arg-type]
    )

    assert sent is True
    assert [url.rsplit("/", 1)[-1] for url, _ in client.posts] == [
        "sendPhoto",
        "sendMessage",
    ]
    assert "https://cdn.example/result.png" in client.posts[1][1]["text"]
    assert client.posts[1][1]["disable_web_page_preview"] is True


@pytest.mark.asyncio
async def test_send_task_success_images_to_user_does_not_fallback_on_timeout() -> None:
    client = _FakeTelegramClient(timeout_photo=True)

    sent = await send_task_success_images_to_user(
        settings=_settings(),
        telegram_id=1,
        task_id=UUID("41b53cfe-b3ed-4bc2-96e7-c32b11439f0c"),
        result_payload={
            "query": {
                "results": [
                    {"url": "https://cdn.example/result.png", "output_type": "png"}
                ]
            }
        },
        client=client,  # type: ignore[arg-type]
    )

    assert sent is True
    assert [url.rsplit("/", 1)[-1] for url, _ in client.posts] == ["sendPhoto"]


@pytest.mark.asyncio
async def test_send_task_success_images_to_user_skips_without_token() -> None:
    client = SimpleNamespace(post=None)

    sent = await send_task_success_images_to_user(
        settings=Settings(telegram_bot_token=None),
        telegram_id=1,
        task_id=UUID("41b53cfe-b3ed-4bc2-96e7-c32b11439f0c"),
        result_payload={
            "query": {
                "results": [
                    {"url": "https://cdn.example/result.png", "output_type": "png"}
                ]
            }
        },
        client=client,  # type: ignore[arg-type]
    )

    assert sent is False


@pytest.mark.asyncio
async def test_send_task_failed_message_to_user_sends_message() -> None:
    client = _FakeTelegramClient()
    task_id = UUID("0a13c4f4-0000-4000-8000-000000000001")

    sent = await send_task_failed_message_to_user(
        settings=_settings(),
        telegram_id=8630043577,
        task_id=task_id,
        error_message="RunningHub query FAILED",
        client=client,  # type: ignore[arg-type]
    )

    assert sent is True
    assert client.posts[0][0].endswith("/sendMessage")
    payload = client.posts[0][1]
    assert payload["chat_id"] == 8630043577
    assert "0A13C4F4" in payload["text"]
    assert "生成失败" in payload["text"]
    assert "不会扣费" in payload["text"]
    assert "预授权冻结会自动释放" in payload["text"]
    assert "RunningHub query FAILED" in payload["text"]
    assert payload["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_send_task_failed_message_to_user_skips_without_token() -> None:
    client = SimpleNamespace(post=None)

    sent = await send_task_failed_message_to_user(
        settings=Settings(telegram_bot_token=None),
        telegram_id=1,
        task_id=UUID("0a13c4f4-0000-4000-8000-000000000001"),
        error_message="failed",
        client=client,  # type: ignore[arg-type]
    )

    assert sent is False


@pytest.mark.asyncio
async def test_send_batch_result_archives_to_user_sends_document(tmp_path) -> None:
    path = tmp_path / "photos_result.zip"
    path.write_bytes(b"zip-bytes")
    client = _FakeMultipartTelegramClient()

    sent = await send_batch_result_archives_to_user(
        settings=_settings(),
        telegram_id=8630043577,
        batch_id=UUID("11111111-1111-4111-8111-111111111111"),
        total_items=2,
        succeeded_items=2,
        failed_items=0,
        archive_paths=[path],
        client=client,  # type: ignore[arg-type]
    )

    assert sent is True
    assert client.posts[0][0].endswith("/sendDocument")
    data = client.posts[0][1]
    files = client.posts[0][2]
    assert data["chat_id"] == 8630043577
    assert "11111111" in data["caption"]
    assert files["document"][0] == "photos_result.zip"
    assert files["document"][1] == b"zip-bytes"
