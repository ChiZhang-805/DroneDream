from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def test_local_storage_roundtrip(tmp_path: Path) -> None:
    from app.storage.local import LocalArtifactStorage

    f = tmp_path / "x.json"
    f.write_text('{"ok":true}', encoding="utf-8")
    storage = LocalArtifactStorage()

    uri = storage.put_file(f, "ignored/x.json", "application/json")
    assert uri == str(f.resolve())
    assert storage.exists(uri)
    assert storage.read_bytes(uri) == b'{"ok":true}'


def test_s3_storage_fake_client(monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACT_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "bucket")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "test-id")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setenv("S3_PREFIX", "prefix/")

    from app.config import get_settings

    get_settings.cache_clear()

    class _Body:
        def read(self) -> bytes:
            return b"payload"

    class _FakeClient:
        def __init__(self) -> None:
            self.uploaded: tuple[str, str, str] | None = None

        def upload_file(self, filename: str, bucket: str, key: str, ExtraArgs=None):
            self.uploaded = (filename, bucket, key)

        def get_object(self, Bucket: str, Key: str):
            assert Bucket == "bucket"
            assert Key == "prefix/jobs/j1/a.txt"
            return {"Body": _Body()}

        def head_object(self, Bucket: str, Key: str):
            assert Bucket == "bucket"
            assert Key == "prefix/jobs/j1/a.txt"
            return {"ok": True}

    fake = _FakeClient()

    class _FakeBoto3:
        @staticmethod
        def client(*args, **kwargs):
            _ = args, kwargs
            return fake

    import sys

    sys.modules["boto3"] = _FakeBoto3()
    import app.storage.s3 as s3_module

    importlib.reload(s3_module)
    storage = s3_module.S3ArtifactStorage()

    uri = storage.put_file(Path("/tmp/a.txt"), "jobs/j1/a.txt", "text/plain")
    assert uri == "s3://bucket/prefix/jobs/j1/a.txt"
    assert storage.exists(uri) is True
    assert storage.read_bytes(uri) == b"payload"

    get_settings.cache_clear()


def test_s3_storage_missing_config_error(monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACT_STORAGE_BACKEND", "s3")
    monkeypatch.delenv("S3_BUCKET", raising=False)

    from app.config import get_settings

    get_settings.cache_clear()

    from app.storage.s3 import S3ArtifactStorage, S3StorageConfigError

    with pytest.raises(S3StorageConfigError):
        S3ArtifactStorage()

    get_settings.cache_clear()
