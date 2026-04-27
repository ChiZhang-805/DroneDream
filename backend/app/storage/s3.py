from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import urlparse

from app.config import get_settings
from app.storage.base import ArtifactStorage, StorageDownload


class S3StorageConfigError(RuntimeError):
    pass


class S3ArtifactStorage(ArtifactStorage):
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.s3_bucket:
            raise S3StorageConfigError("S3_BUCKET is required when ARTIFACT_STORAGE_BACKEND=s3")
        if not settings.s3_access_key_id or not settings.s3_secret_access_key:
            raise S3StorageConfigError(
                "S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY are required "
                "when ARTIFACT_STORAGE_BACKEND=s3"
            )
        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_prefix
        if self.prefix and not self.prefix.endswith("/"):
            self.prefix = f"{self.prefix}/"
        try:
            import boto3  # type: ignore
        except ModuleNotFoundError as exc:
            raise S3StorageConfigError(
                "boto3 is not installed; install backend storage dependencies"
            ) from exc
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
        )

    def put_file(self, local_path: str, key: str, content_type: str | None = None) -> str:
        object_key = f"{self.prefix}{key}" if self.prefix else key
        extra: dict[str, str] = {}
        if content_type:
            extra["ContentType"] = content_type
        self._client.upload_file(local_path, self.bucket, object_key, ExtraArgs=extra or None)
        return f"s3://{self.bucket}/{object_key}"

    def open_for_download(self, storage_uri: str) -> StorageDownload:
        bucket, key = _parse_s3_uri(storage_uri)
        res = self._client.get_object(Bucket=bucket, Key=key)
        content = res["Body"].read()
        ct = (
            res.get("ContentType")
            or mimetypes.guess_type(Path(key).name)[0]
            or "application/octet-stream"
        )
        return StorageDownload(content=content, content_type=ct, filename=Path(key).name)

    def exists(self, storage_uri: str) -> bool:
        bucket, key = _parse_s3_uri(storage_uri)
        try:
            self._client.head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path:
        raise S3StorageConfigError(f"Invalid s3 uri: {uri}")
    return parsed.netloc, parsed.path.lstrip("/")
