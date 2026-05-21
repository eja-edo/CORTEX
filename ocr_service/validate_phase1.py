"""
Phase 1 Validation Script

Run this after starting the OCR service to verify all components work.
Usage: python validate_phase1.py
"""

import asyncio
import redis.asyncio as redis
from config import settings


async def validate():
    """Run all Phase 1 validation checks."""
    print("=" * 60)
    print("Phase 1 Validation Checklist")
    print("=" * 60)
    
    checks = []
    
    # 1. Redis connection
    try:
        r = redis.from_url(settings.redis_url)
        await r.ping()
        checks.append(("Redis connection", True, "OK"))
        await r.close()
    except Exception as e:
        checks.append(("Redis connection", False, str(e)))
    
    # 2. Consumer group exists
    try:
        r = redis.from_url(settings.redis_url)
        groups = await r.xinfo_groups(settings.input_stream_key)
        group_names = [
            g["name"].decode() if isinstance(g["name"], bytes) else g["name"]
            for g in groups
        ]
        if settings.consumer_group in group_names:
            checks.append((f"Consumer group '{settings.consumer_group}'", True, "OK"))
        else:
            checks.append((f"Consumer group '{settings.consumer_group}'", False, "Not found"))
        await r.close()
    except Exception as e:
        checks.append((f"Consumer group '{settings.consumer_group}'", False, str(e)))
    
    # 3. MongoDB connection
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(settings.mongodb_url)
        await client.admin.command("ping")
        checks.append(("MongoDB connection", True, "OK"))
        client.close()
    except Exception as e:
        checks.append(("MongoDB connection", False, str(e)))
    
    # 4. MinIO connection
    try:
        import boto3
        from botocore.client import Config
        scheme = "https" if settings.minio_secure else "http"
        endpoint = settings.minio_endpoint.removeprefix("http://").removeprefix("https://")
        client = boto3.client(
            "s3",
            endpoint_url=f"{scheme}://{endpoint}",
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            config=Config(signature_version="s3v4"),
        )
        client.list_buckets()
        checks.append(("MinIO connection", True, "OK"))
    except Exception as e:
        checks.append(("MinIO connection", False, str(e)))
    
    # 5. Pipeline imports
    try:
        from pipeline.video_pipeline import run_pipeline, Config
        from pipeline.layout_processor import process_metadata_file
        checks.append(("Pipeline imports", True, "OK"))
    except Exception as e:
        checks.append(("Pipeline imports", False, str(e)))
    
    # 6. Storage imports
    try:
        from storage.minio_client import MinIOClient
        from storage.mongo_client import MongoOCRWriter
        checks.append(("Storage imports", True, "OK"))
    except Exception as e:
        checks.append(("Storage imports", False, str(e)))
    
    # Print results
    print()
    for name, passed, detail in checks:
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {name}: {detail}")
    
    print()
    passed_count = sum(1 for _, passed, _ in checks if passed)
    total = len(checks)
    print(f"Result: {passed_count}/{total} checks passed")
    print("=" * 60)
    
    return all(passed for _, passed, _ in checks)


if __name__ == "__main__":
    success = asyncio.run(validate())
    exit(0 if success else 1)
