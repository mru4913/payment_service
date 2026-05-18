"""common/storage.py 单元测试。"""

from __future__ import annotations

import io
from datetime import date, timedelta
from pathlib import Path

import pytest

from common.storage import LocalStorage, resolve_file_ref


@pytest.fixture()
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(base_dir=tmp_path)


class TestSave:
    def test_save_bytes(self, storage: LocalStorage) -> None:
        path = storage.save(b"hello", filename="test.txt")
        assert path.exists()
        assert path.read_bytes() == b"hello"
        assert path.suffix == ".txt"

    def test_save_binary_io(self, storage: LocalStorage) -> None:
        buf = io.BytesIO(b"world")
        path = storage.save(buf, suffix=".bin")
        assert path.read_bytes() == b"world"
        assert path.suffix == ".bin"

    def test_files_in_date_subdir(self, storage: LocalStorage) -> None:
        path = storage.save(b"x", filename="a.png")
        today = date.today().isoformat()
        assert today in str(path)


class TestCleanup:
    def test_removes_old_dirs(self, storage: LocalStorage) -> None:
        old_date = (date.today() - timedelta(days=5)).isoformat()
        old_dir = storage.base_dir / old_date
        old_dir.mkdir(parents=True)
        (old_dir / "file.jpg").write_bytes(b"old")

        today_dir = storage.base_dir / date.today().isoformat()
        today_dir.mkdir(parents=True)
        (today_dir / "file.jpg").write_bytes(b"new")

        removed = storage.cleanup(retain_days=3)
        assert removed == 1
        assert not old_dir.exists()
        assert today_dir.exists()

    def test_no_error_on_empty(self, storage: LocalStorage) -> None:
        assert storage.cleanup(retain_days=1) == 0


class TestResolveFileRef:
    @pytest.mark.asyncio()
    async def test_local_file(self, tmp_path: Path) -> None:
        f = tmp_path / "img.png"
        f.write_bytes(b"\x89PNG")
        content, name, ct = await resolve_file_ref(str(f))
        assert content == b"\x89PNG"
        assert name == "img.png"
        assert ct is not None and "png" in ct

    @pytest.mark.asyncio()
    async def test_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            await resolve_file_ref("/nonexistent/path.jpg")
