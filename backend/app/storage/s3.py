from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

from app.config import get_settings
from app.storage.base import ArtifactStorage


class S3StorageConfigError(RuntimeError):
    """Raised when S3 backend is requested with invalid/missing config."""


class S3ArtifactStorage(ArtifactStorage):
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.s3_bucket:
            raise S3StorageConfigError(
                "S3 backend requires S3_BUCKET when ARTIFACT_STORAGE_BACKEND=s3"
            )
        if not settings.s3_access_key_id or not settings.s3_secret_access_key:
            raise S3StorageConfigError(
                "S3 backend requires S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY "
                "when ARTIFACT_STORAGE_BACKEND=s3"
            )
        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_prefix
        if self.prefix and not self.prefix.endswith("/"):
            self.prefix = f"{self.prefix}/"
        try:
            import boto3
            from botocore.config import Config
        except ModuleNotFoundError as exc:
            raise S3StorageConfigError(
                "boto3 is not installed; install backend[storage] dependencies"
            ) from exc
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            config=Config(
                connect_timeout=settings.s3_connect_timeout_seconds,
                read_timeout=settings.s3_read_timeout_seconds,
                retries={
                    "max_attempts": settings.s3_max_attempts,
                    "mode": "standard",
                },
            ),
        )

    def put_file(self, local_path: Path, key: str, content_type: str | None = None) -> str:
        object_key = f"{self.prefix}{key}" if self.prefix else key
        extra: dict[str, str] = {}
        if content_type:
            extra["ContentType"] = content_type
        self._client.upload_file(
            str(local_path), self.bucket, object_key, ExtraArgs=extra or None
        )
        return f"s3://{self.bucket}/{object_key}"

    def _configured_location(self, storage_uri: str) -> tuple[str, str]:
        """Resolve only objects inside this backend's configured namespace."""

        bucket, key = _parse_s3_uri(storage_uri)
        if bucket != self.bucket:
            raise S3StorageConfigError("Refusing to access an object outside configured bucket")
        if self.prefix and not key.startswith(self.prefix):
            raise S3StorageConfigError("Refusing to access an object outside configured prefix")
        return bucket, key

    def read_bytes(self, storage_uri: str) -> bytes:
        bucket, key = self._configured_location(storage_uri)
        response = self._client.get_object(Bucket=bucket, Key=key)
        return cast(bytes, response["Body"].read())

    def content_digest(self, storage_uri: str) -> tuple[str, int]:
        bucket, key = self._configured_location(storage_uri)
        response = self._client.get_object(Bucket=bucket, Key=key)
        body = response["Body"]
        digest = hashlib.sha256()
        size = 0
        try:
            while True:
                chunk = body.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()
        return digest.hexdigest(), size

    def exists(self, storage_uri: str) -> bool:
        bucket, key = self._configured_location(storage_uri)
        try:
            self._client.head_object(Bucket=bucket, Key=key)
            return True
        except Exception as exc:
            # An outage, authorization error, or throttling response must not
            # be misreported as "file missing". Only S3's explicit not-found
            # responses are safe to collapse to False.
            response = getattr(exc, "response", None)
            error = response.get("Error", {}) if isinstance(response, dict) else {}
            code = str(error.get("Code", "")) if isinstance(error, dict) else ""
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def delete(self, storage_uri: str) -> None:
        bucket, key = self._configured_location(storage_uri)
        self._client.delete_object(Bucket=bucket, Key=key)

    def presign_download(
        self, storage_uri: str, *, expires_seconds: int | None = None
    ) -> str | None:
        bucket, key = self._configured_location(storage_uri)
        expiry = expires_seconds or get_settings().artifact_presign_expiry_seconds
        return str(
            self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expiry,
            )
        )

    def check_health(self) -> None:
        self._client.head_bucket(Bucket=self.bucket)


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    key = parsed.path.lstrip("/")
    if (
        parsed.scheme != "s3"
        or not parsed.netloc
        or not key
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise S3StorageConfigError(f"Invalid s3 uri: {uri}")
    return parsed.netloc, key
