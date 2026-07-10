from __future__ import annotations

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

    def read_bytes(self, storage_uri: str) -> bytes:
        bucket, key = _parse_s3_uri(storage_uri)
        response = self._client.get_object(Bucket=bucket, Key=key)
        return cast(bytes, response["Body"].read())

    def exists(self, storage_uri: str) -> bool:
        bucket, key = _parse_s3_uri(storage_uri)
        try:
            self._client.head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False

    def delete(self, storage_uri: str) -> None:
        bucket, key = _parse_s3_uri(storage_uri)
        self._client.delete_object(Bucket=bucket, Key=key)

    def presign_download(
        self, storage_uri: str, *, expires_seconds: int | None = None
    ) -> str | None:
        bucket, key = _parse_s3_uri(storage_uri)
        if bucket != self.bucket:
            raise S3StorageConfigError(
                f"Refusing to presign an object outside configured bucket {self.bucket!r}"
            )
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
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path:
        raise S3StorageConfigError(f"Invalid s3 uri: {uri}")
    return parsed.netloc, parsed.path.lstrip("/")
