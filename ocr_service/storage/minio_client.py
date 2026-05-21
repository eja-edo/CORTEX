"""
MinIO Client for OCR Service

Handles downloading videos from MinIO/S3 storage.
"""

import boto3
from botocore.client import Config
from pathlib import Path
from uuid import uuid4
from config import settings


class MinIOClient:
    """MinIO client for downloading video files."""
    
    def __init__(self):
        scheme = "https" if settings.minio_secure else "http"
        endpoint = settings.minio_endpoint.removeprefix("http://").removeprefix("https://")
        self.client = boto3.client(
            "s3",
            endpoint_url=f"{scheme}://{endpoint}",
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            config=Config(signature_version="s3v4"),
        )
        self.bucket = settings.minio_bucket

    def download(self, object_key: str, task_id: str) -> Path:
        """
        Download a file from MinIO to local temp directory.
        
        Args:
            object_key: MinIO object key (path)
            task_id: Task ID for unique filename
            
        Returns:
            Path to downloaded file
        """
        suffix = Path(object_key).suffix or ".webm"
        local_path = Path(settings.temp_dir) / f"{task_id}_{uuid4().hex[:8]}{suffix}"
        local_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.client.download_file(self.bucket, object_key, str(local_path))
        
        if not local_path.exists():
            raise FileNotFoundError(f"Download failed: {local_path}")
        
        return local_path
