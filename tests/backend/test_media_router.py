"""媒体上传 API。"""

from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio

from backend.api.auth import verify_api_key
from backend.api.main import create_api_app
from backend.api.routers import media as media_mod

_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"0" * 16


@pytest_asyncio.fixture
async def client_no_auth():
    app = create_api_app()

    async def no_auth():
        return None

    app.dependency_overrides[verify_api_key] = no_auth
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_upload_media_returns_file_ref(client_no_auth):
    with patch("backend.api.routers.media.save_upload", return_value="/tmp/a.jpg"):
        r = await client_no_auth.post(
            "/media/uploads",
            headers={"X-Request-ID": "test-request-1"},
            files={"file": ("face.jpg", _JPEG_BYTES, "image/jpeg")},
        )

    assert r.status_code == 200
    assert r.headers["X-Request-ID"] == "test-request-1"
    data = r.json()
    assert data["file_ref"] == "/tmp/a.jpg"
    assert data["filename"] == "face.jpg"
    assert data["content_type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_upload_media_rejects_non_image(client_no_auth):
    r = await client_no_auth.post(
        "/media/uploads",
        files={"file": ("x.txt", b"txt", "text/plain")},
    )

    assert r.status_code == 400


@pytest.mark.asyncio
async def test_upload_media_rejects_fake_image_bytes(client_no_auth):
    r = await client_no_auth.post(
        "/media/uploads",
        files={"file": ("face.jpg", b"not an image", "image/jpeg")},
    )

    assert r.status_code == 400


@pytest.mark.asyncio
async def test_upload_media_rejects_oversized_file(client_no_auth, monkeypatch):
    monkeypatch.setattr(media_mod.settings, "upload_max_bytes", 3)
    r = await client_no_auth.post(
        "/media/uploads",
        files={"file": ("face.jpg", _JPEG_BYTES, "image/jpeg")},
    )

    assert r.status_code == 413
