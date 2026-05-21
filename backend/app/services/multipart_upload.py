from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class MultipartStorageError(Exception):
    """Raised when MinIO/S3 multipart operations fail."""


class MinIOMultipartService:
    """Service for S3-compatible multipart operations against MinIO."""

    def __init__(self) -> None:
        self.bucket = settings.MINIO_BUCKET
        self.client = boto3.client(
            "s3",
            endpoint_url=self._endpoint_url(),
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            region_name=settings.MINIO_REGION,
            config=Config(signature_version="s3v4", retries={"max_attempts": 4, "mode": "standard"}),
        )

        if settings.MINIO_AUTO_CREATE_BUCKET:
            self._ensure_bucket()

    def _endpoint_url(self) -> str:
        scheme = "https" if settings.MINIO_SECURE else "http"
        endpoint = settings.MINIO_ENDPOINT.removeprefix("http://").removeprefix("https://")
        return f"{scheme}://{endpoint}"

    def _ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    def _is_no_such_bucket(self, exc: ClientError) -> bool:
        code = exc.response.get("Error", {}).get("Code", "")
        return code in {"NoSuchBucket", "404"}

    def build_object_key(self, user_id: UUID, filename: str | None = None) -> str:
        suffix = "webm"
        if filename and "." in filename:
            suffix = filename.rsplit(".", 1)[-1].lower()[:10] or "webm"
        now = datetime.utcnow()
        return f"videos/{user_id}/{now:%Y/%m/%d}/{uuid4()}.{suffix}"

    def create_multipart_upload(self, object_key: str, content_type: str | None = None) -> str:
        params = {"Bucket": self.bucket, "Key": object_key}
        if content_type:
            params["ContentType"] = content_type

        try:
            response = self.client.create_multipart_upload(**params)
        except ClientError as exc:
            if self._is_no_such_bucket(exc):
                if settings.MINIO_AUTO_CREATE_BUCKET:
                    logger.warning("Bucket '%s' not found, creating automatically", self.bucket)
                    try:
                        self._ensure_bucket()
                        response = self.client.create_multipart_upload(**params)
                    except ClientError as retry_exc:
                        logger.exception("Failed to create multipart upload after bucket auto-create")
                        raise MultipartStorageError(
                            f"Failed to initialize multipart upload for bucket '{self.bucket}'"
                        ) from retry_exc
                else:
                    raise MultipartStorageError(
                        f"Bucket '{self.bucket}' does not exist. Set MINIO_BUCKET correctly or enable MINIO_AUTO_CREATE_BUCKET=true"
                    ) from exc
            else:
                logger.exception("Failed to create multipart upload")
                raise MultipartStorageError("Failed to initialize multipart upload") from exc

        upload_id = response.get("UploadId")
        if not upload_id:
            raise MultipartStorageError("Missing upload_id from storage provider")
        return upload_id

    def presign_upload_part(self, object_key: str, upload_id: str, part_number: int, expires_seconds: int) -> str:
        try:
            return self.client.generate_presigned_url(
                ClientMethod="upload_part",
                Params={
                    "Bucket": self.bucket,
                    "Key": object_key,
                    "UploadId": upload_id,
                    "PartNumber": part_number,
                },
                ExpiresIn=expires_seconds,
                HttpMethod="PUT",
            )
        except ClientError as exc:
            logger.exception("Failed to generate presigned url")
            raise MultipartStorageError("Failed to generate presigned URL") from exc

    def presign_get_object(self, object_key: str, expires_seconds: int, disposition: str = "inline") -> str:
        try:
            params = {
                "Bucket": self.bucket,
                "Key": object_key,
                "ResponseContentDisposition": disposition,
            }
            return self.client.generate_presigned_url(
                ClientMethod="get_object",
                Params=params,
                ExpiresIn=expires_seconds,
                HttpMethod="GET",
            )
        except ClientError as exc:
            logger.exception("Failed to generate media access URL")
            raise MultipartStorageError("Failed to generate media access URL") from exc

    def complete_multipart_upload(self, object_key: str, upload_id: str, parts: list[dict]) -> None:
        try:
            self.client.complete_multipart_upload(
                Bucket=self.bucket,
                Key=object_key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )
        except ClientError as exc:
            logger.exception("Failed to complete multipart upload")
            raise MultipartStorageError("Failed to complete multipart upload") from exc

    def abort_multipart_upload(self, object_key: str, upload_id: str) -> None:
        try:
            self.client.abort_multipart_upload(
                Bucket=self.bucket,
                Key=object_key,
                UploadId=upload_id,
            )
        except ClientError:
            logger.warning("Failed abort multipart upload for key=%s upload_id=%s", object_key, upload_id)
