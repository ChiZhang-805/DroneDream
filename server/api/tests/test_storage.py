from __future__ import annotations

import importlib
import io
import sys
from pathlib import Path
from types import ModuleType

import pytest


def test_local_storage_roundtrip(tmp_path: Path, monkeypatch) -> None:
    from app.config import get_settings
    from app.storage.local import LocalArtifactStorage

    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))
    get_settings.cache_clear()
    f = tmp_path / "x.json"
    f.write_text('{"ok":true}', encoding="utf-8")
    storage = LocalArtifactStorage()

    uri = storage.put_file(f, "ignored/x.json", "application/json")
    assert uri == str(f.resolve())
    assert storage.exists(uri)
    assert storage.read_bytes(uri) == b'{"ok":true}'
    assert storage.content_digest(uri) == (
        "4062edaf750fb8074e7e83e0c9028c94e32468a8b6f1614774328ef045150f93",
        11,
    )
    copied = io.BytesIO()
    assert storage.copy_to(uri, copied) == (
        "4062edaf750fb8074e7e83e0c9028c94e32468a8b6f1614774328ef045150f93",
        11,
    )
    assert copied.getvalue() == b'{"ok":true}'
    with pytest.raises(ValueError, match="outside allowed roots"):
        storage.read_bytes(str(tmp_path.parent / "outside.json"))
    get_settings.cache_clear()


def test_s3_storage_fake_client(monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACT_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "bucket")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "test-id")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setenv("S3_PREFIX", "prefix/")
    monkeypatch.setenv("S3_CONNECT_TIMEOUT_SECONDS", "2")
    monkeypatch.setenv("S3_READ_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("S3_MAX_ATTEMPTS", "4")

    from app.config import get_settings

    get_settings.cache_clear()

    class _Body:
        def __init__(self) -> None:
            self._offset = 0
            self.closed = False

        def read(self, size: int = -1) -> bytes:
            payload = b"payload"
            if self._offset >= len(payload):
                return b""
            end = len(payload) if size < 0 else self._offset + size
            chunk = payload[self._offset : end]
            self._offset += len(chunk)
            return chunk

        def close(self) -> None:
            self.closed = True

    class _FakeClient:
        def __init__(self) -> None:
            self.uploaded: tuple[str, str, str] | None = None
            self.health_checked = False
            self.bodies: list[_Body] = []

        def upload_file(self, filename: str, bucket: str, key: str, ExtraArgs=None):
            self.uploaded = (filename, bucket, key)

        def get_object(self, Bucket: str, Key: str):
            assert Bucket == "bucket"
            assert Key == "prefix/jobs/j1/a.txt"
            body = _Body()
            self.bodies.append(body)
            return {"Body": body}

        def head_object(self, Bucket: str, Key: str):
            assert Bucket == "bucket"
            assert Key == "prefix/jobs/j1/a.txt"
            return {"ok": True}

        def generate_presigned_url(self, operation: str, Params, ExpiresIn: int):
            assert operation == "get_object"
            assert Params == {"Bucket": "bucket", "Key": "prefix/jobs/j1/a.txt"}
            assert ExpiresIn == 120
            return "https://objects.example/signed"

        def head_bucket(self, Bucket: str):
            assert Bucket == "bucket"
            self.health_checked = True

    fake = _FakeClient()
    client_call: dict[str, object] = {}

    class _FakeConfig:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    fake_boto3 = ModuleType("boto3")

    def fake_client(*args, **kwargs):
        client_call["args"] = args
        client_call["kwargs"] = kwargs
        return fake

    fake_boto3.client = fake_client  # type: ignore[attr-defined]
    fake_botocore = ModuleType("botocore")
    fake_botocore_config = ModuleType("botocore.config")
    fake_botocore_config.Config = _FakeConfig  # type: ignore[attr-defined]
    fake_botocore.config = fake_botocore_config  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setitem(sys.modules, "botocore", fake_botocore)
    monkeypatch.setitem(sys.modules, "botocore.config", fake_botocore_config)
    import app.storage.s3 as s3_module

    importlib.reload(s3_module)
    storage = s3_module.S3ArtifactStorage()
    assert client_call["args"] == ("s3",)
    client_kwargs = client_call["kwargs"]
    assert isinstance(client_kwargs, dict)
    config = client_kwargs["config"]
    assert isinstance(config, _FakeConfig)
    assert config.kwargs == {
        "connect_timeout": 2.0,
        "read_timeout": 7.0,
        "retries": {"max_attempts": 4, "mode": "standard"},
    }

    uri = storage.put_file(Path("/tmp/a.txt"), "jobs/j1/a.txt", "text/plain")
    assert uri == "s3://bucket/prefix/jobs/j1/a.txt"
    assert storage.exists(uri) is True
    assert storage.read_bytes(uri) == b"payload"
    assert storage.content_digest(uri) == (
        "239f59ed55e737c77147cf55ad0c1b030b6d7ee748a7426952f9b852d5a935e5",
        7,
    )
    copied = io.BytesIO()
    assert storage.copy_to(uri, copied) == (
        "239f59ed55e737c77147cf55ad0c1b030b6d7ee748a7426952f9b852d5a935e5",
        7,
    )
    assert copied.getvalue() == b"payload"
    assert all(body.closed for body in fake.bodies)

    class _PartialDestination:
        def write(self, content: bytes) -> int:
            return max(0, len(content) - 1)

    with pytest.raises(OSError, match="partial write"):
        storage.copy_to(uri, _PartialDestination())  # type: ignore[arg-type]
    assert all(body.closed for body in fake.bodies)
    assert storage.presign_download(uri, expires_seconds=120) == (
        "https://objects.example/signed"
    )
    with pytest.raises(s3_module.S3StorageConfigError, match="outside configured bucket"):
        storage.read_bytes("s3://other/prefix/jobs/j1/a.txt")
    with pytest.raises(s3_module.S3StorageConfigError, match="outside configured prefix"):
        storage.delete("s3://bucket/other/jobs/j1/a.txt")
    storage.check_health()
    assert fake.health_checked is True

    class _MissingObjectError(Exception):
        response = {"Error": {"Code": "NoSuchKey"}}

    class _MissingClient:
        def head_object(self, **_kwargs):
            raise _MissingObjectError

    storage._client = _MissingClient()
    assert storage.exists(uri) is False

    class _UnavailableClient:
        def head_object(self, **_kwargs):
            raise RuntimeError("temporary S3 outage")

    storage._client = _UnavailableClient()
    with pytest.raises(RuntimeError, match="temporary S3 outage"):
        storage.exists(uri)

    for invalid_uri in ("s3://bucket/", "s3://bucket/key?versionId=secret"):
        with pytest.raises(s3_module.S3StorageConfigError, match="Invalid s3 uri"):
            s3_module._parse_s3_uri(invalid_uri)

    get_settings.cache_clear()


def test_local_storage_presign_falls_back_to_api_streaming(tmp_path: Path) -> None:
    from app.storage.local import LocalArtifactStorage

    storage = LocalArtifactStorage()
    assert storage.presign_download(str(tmp_path / "x")) is None


def test_s3_storage_missing_config_error(monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACT_STORAGE_BACKEND", "s3")
    monkeypatch.delenv("S3_BUCKET", raising=False)

    from app.config import get_settings

    get_settings.cache_clear()

    from app.storage.s3 import S3ArtifactStorage, S3StorageConfigError

    with pytest.raises(S3StorageConfigError):
        S3ArtifactStorage()

    get_settings.cache_clear()
