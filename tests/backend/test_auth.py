"""API 鉴权单元测试"""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from backend.api.auth import verify_api_key


class TestVerifyApiKey:
    @pytest.mark.asyncio
    async def test_no_config_allows_all(self):
        with patch("backend.api.auth.settings") as mock_settings:
            mock_settings.api_key = None
            await verify_api_key(None)
            await verify_api_key("anything")

    @pytest.mark.asyncio
    async def test_correct_key_passes(self):
        with patch("backend.api.auth.settings") as mock_settings:
            mock_settings.api_key = "secret-123"
            await verify_api_key("secret-123")

    @pytest.mark.asyncio
    async def test_wrong_key_raises_401(self):
        with patch("backend.api.auth.settings") as mock_settings:
            mock_settings.api_key = "secret-123"
            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key("wrong-key")
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_key_raises_401(self):
        with patch("backend.api.auth.settings") as mock_settings:
            mock_settings.api_key = "secret-123"
            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(None)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_empty_string_key_raises_401(self):
        with patch("backend.api.auth.settings") as mock_settings:
            mock_settings.api_key = "secret-123"
            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key("")
            assert exc_info.value.status_code == 401
