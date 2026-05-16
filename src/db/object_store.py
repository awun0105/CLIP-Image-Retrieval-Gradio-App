"""MinIO-backed object store wrapper for image artefacts."""

from __future__ import annotations

import io
import logging
from datetime import timedelta
from urllib.parse import urlsplit

from minio import Minio
from minio.error import S3Error

from config import Settings

logger = logging.getLogger(__name__)


class ObjectStore:
    """Thin wrapper around the MinIO client scoped to a single bucket."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.bucket = settings.minio_bucket
        self.client = Minio(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
            region=settings.minio_region,
        )
        self.presign_client = self.client
        if settings.minio_public_endpoint:
            public_endpoint, public_secure = _parse_minio_endpoint(
                settings.minio_public_endpoint,
                default_secure=settings.minio_secure,
            )
            self.presign_client = Minio(
                endpoint=public_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=public_secure,
                region=settings.minio_region,
            )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)
            logger.info("Created MinIO bucket: %s", self.bucket)

    def upload_file(self, file_path: str, object_key: str) -> None:
        self.client.fput_object(self.bucket, object_key, file_path)

    def upload_bytes(self, data: bytes, object_key: str, content_type: str = "image/jpeg") -> None:
        self.client.put_object(
            self.bucket,
            object_key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )

    def get_presigned_url(self, object_key: str, expires: int = 3600) -> str:
        return self.presign_client.presigned_get_object(
            self.bucket, object_key, expires=timedelta(seconds=expires)
        )

    def get_object(self, object_key: str) -> bytes:
        response = self.client.get_object(self.bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def object_exists(self, object_key: str) -> bool:
        try:
            self.client.stat_object(self.bucket, object_key)
            return True
        except S3Error:
            return False

    def list_objects(self, prefix: str = "") -> list[str]:
        return [obj.object_name for obj in self.client.list_objects(self.bucket, prefix=prefix)]


def _parse_minio_endpoint(public_endpoint: str, *, default_secure: bool) -> tuple[str, bool]:
    """Return a MinIO SDK endpoint and secure flag from a public endpoint setting."""
    public = public_endpoint.strip().rstrip("/")
    if "://" not in public:
        return public, default_secure

    parsed = urlsplit(public)
    return parsed.netloc, parsed.scheme == "https"
