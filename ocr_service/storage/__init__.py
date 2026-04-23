"""Storage modules."""

from .minio_client import MinIOClient
from .mongo_client import MongoOCRWriter

__all__ = ["MinIOClient", "MongoOCRWriter"]
