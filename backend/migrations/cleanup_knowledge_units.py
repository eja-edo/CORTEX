"""
Migration script: Clean up knowledge_units collection by removing deprecated fields.
Run this after updating the schema.

Removes these fields from all knowledge_units documents:
  - user_id
  - ocr_processed_id
  - source_has_ocr
  - source_has_transcript
  - context
  - error_type
  - resolution
  - reusability
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings


async def cleanup_knowledge_units():
    """Remove deprecated fields from knowledge_units collection."""
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    collection = db["knowledge_units"]

    # Fields to remove
    fields_to_unset = {
        "user_id": "",
        "ocr_processed_id": "",
        "source_has_ocr": "",
        "source_has_transcript": "",
        "context": "",
        "error_type": "",
        "resolution": "",
        "reusability": "",
    }

    # Update all documents to remove these fields
    result = await collection.update_many(
        {},  # Empty filter = all documents
        {"$unset": fields_to_unset}
    )

    print(f"✅ Cleanup complete:")
    print(f"   Matched documents: {result.matched_count}")
    print(f"   Modified documents: {result.modified_count}")

    client.close()


if __name__ == "__main__":
    asyncio.run(cleanup_knowledge_units())
