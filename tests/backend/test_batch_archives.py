"""Batch archive extraction and validation."""

import io
import tarfile
import zipfile

import pytest

from backend.services.batch_archives import (
    BatchArchiveError,
    extract_batch_archive,
    result_archive_name,
    result_relative_path,
)
from backend.storage import local as storage_local

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 12


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _tar_gz(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_extract_zip_preserves_relative_paths(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(storage_local.settings, "upload_dir", str(tmp_path))
    monkeypatch.setattr(storage_local, "_default_storage", None)

    archive = extract_batch_archive(
        content=_zip(
            {
                "girl/001.png": PNG_BYTES,
                "__MACOSX/ignored.png": PNG_BYTES,
                ".DS_Store": b"ignored",
            }
        ),
        filename="photos.zip",
        max_items=20,
        max_unpacked_bytes=1024 * 1024,
        max_image_bytes=1024 * 1024,
    )

    assert archive.archive_format == "zip"
    assert [img.relative_path for img in archive.images] == ["girl/001.png"]
    assert archive.images[0].file_ref.endswith(".png")


def test_extract_tar_gz_preserves_relative_paths(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(storage_local.settings, "upload_dir", str(tmp_path))
    monkeypatch.setattr(storage_local, "_default_storage", None)

    archive = extract_batch_archive(
        content=_tar_gz({"nested/001.webp": b"RIFFxxxxWEBP" + b"\x00" * 8}),
        filename="photos.tar.gz",
        max_items=20,
        max_unpacked_bytes=1024 * 1024,
        max_image_bytes=1024 * 1024,
    )

    assert archive.archive_format == "tar.gz"
    assert [img.relative_path for img in archive.images] == ["nested/001.webp"]


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("../evil.png", "invalid_archive"),
        ("/abs/evil.png", "invalid_archive"),
    ],
)
def test_extract_zip_rejects_unsafe_paths(name: str, code: str, tmp_path, monkeypatch):
    monkeypatch.setattr(storage_local.settings, "upload_dir", str(tmp_path))
    monkeypatch.setattr(storage_local, "_default_storage", None)

    with pytest.raises(BatchArchiveError) as exc:
        extract_batch_archive(
            content=_zip({name: PNG_BYTES}),
            filename="bad.zip",
            max_items=20,
            max_unpacked_bytes=1024 * 1024,
            max_image_bytes=1024 * 1024,
        )

    assert exc.value.code == code


def test_extract_zip_rejects_fake_image_bytes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(storage_local.settings, "upload_dir", str(tmp_path))
    monkeypatch.setattr(storage_local, "_default_storage", None)

    with pytest.raises(BatchArchiveError) as exc:
        extract_batch_archive(
            content=_zip({"fake.png": b"not actually an image"}),
            filename="bad.zip",
            max_items=20,
            max_unpacked_bytes=1024 * 1024,
            max_image_bytes=1024 * 1024,
        )

    assert "图片内容无效" in exc.value.message


def test_extract_zip_cleans_saved_images_when_later_member_fails(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(storage_local.settings, "upload_dir", str(tmp_path))
    monkeypatch.setattr(storage_local, "_default_storage", None)

    with pytest.raises(BatchArchiveError):
        extract_batch_archive(
            content=_zip({"ok.png": PNG_BYTES, "bad.png": b"not an image"}),
            filename="bad.zip",
            max_items=20,
            max_unpacked_bytes=1024 * 1024,
            max_image_bytes=1024 * 1024,
        )

    assert list(tmp_path.rglob("*.*")) == []


def test_extract_zip_counts_large_non_image_toward_unpacked_limit(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(storage_local.settings, "upload_dir", str(tmp_path))
    monkeypatch.setattr(storage_local, "_default_storage", None)

    with pytest.raises(BatchArchiveError) as exc:
        extract_batch_archive(
            content=_zip({"huge.txt": b"x" * 2048, "ok.png": PNG_BYTES}),
            filename="huge.zip",
            max_items=20,
            max_unpacked_bytes=1024,
            max_image_bytes=1024 * 1024,
        )

    assert "总大小超过限制" in exc.value.message


def test_extract_zip_rejects_image_declared_over_limit_before_save(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(storage_local.settings, "upload_dir", str(tmp_path))
    monkeypatch.setattr(storage_local, "_default_storage", None)
    saved = []

    def fake_save(_content, *, filename=None, suffix=""):
        saved.append(filename)
        return str(tmp_path / (filename or "upload"))

    monkeypatch.setattr("backend.services.batch_archives.save_upload", fake_save)

    with pytest.raises(BatchArchiveError) as exc:
        extract_batch_archive(
            content=_zip({"too_big.png": PNG_BYTES}),
            filename="big.zip",
            max_items=20,
            max_unpacked_bytes=1024 * 1024,
            max_image_bytes=len(PNG_BYTES) - 1,
        )

    assert "单张图片超过大小限制" in exc.value.message
    assert saved == []


def test_extract_zip_rejects_too_many_images_before_saving_extra(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(storage_local.settings, "upload_dir", str(tmp_path))
    monkeypatch.setattr(storage_local, "_default_storage", None)
    saved: list[str | None] = []

    def fake_save(_content, *, filename=None, suffix=""):
        saved.append(filename)
        return str(tmp_path / (filename or "upload"))

    monkeypatch.setattr("backend.services.batch_archives.save_upload", fake_save)

    with pytest.raises(BatchArchiveError) as exc:
        extract_batch_archive(
            content=_zip({"1.png": PNG_BYTES, "2.png": PNG_BYTES}),
            filename="too_many.zip",
            max_items=1,
            max_unpacked_bytes=1024 * 1024,
            max_image_bytes=1024 * 1024,
        )

    assert "最多支持 1 张图片" in exc.value.message
    assert saved == ["1.png"]


def test_result_names_follow_source_archive_format() -> None:
    assert result_archive_name("photos.zip", "zip") == "photos_result.zip"
    assert result_archive_name("photos.tar", "tar") == "photos_result.tar"
    assert (
        result_archive_name("photos.tar.gz", "tar.gz")
        == "photos_result.tar.gz"
    )
    assert result_relative_path("a/b/c.jpg") == "a/b/c.png"
