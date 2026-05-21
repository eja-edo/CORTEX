"""
Transcript Waiter with Heartbeat

Polls MongoDB until transcript is available or timeout.
Includes heartbeat logging for log aggregation systems.
"""

import asyncio
import logging
from storage.mongo_client import MongoOCRWriter

logger = logging.getLogger(__name__)


async def wait_for_transcript(
    asset_id: str,
    mongo: MongoOCRWriter,
    timeout: float = 300.0,
    poll_interval: float = 5.0,
) -> bool:
    """
    Poll MongoDB until transcript exists for asset_id or timeout.
    
    Args:
        asset_id: Asset/video ID to check
        mongo: MongoDB client instance
        timeout: Maximum seconds to wait (0 = check once)
        poll_interval: Seconds between polls
        
    Returns:
        True if transcript is available, False if timed out
    """
    if timeout <= 0:
        return await mongo.has_transcript(asset_id)
    
    elapsed = 0.0
    while elapsed < timeout:
        if await mongo.has_transcript(asset_id):
            logger.info(f"Transcript ready for {asset_id} after {elapsed:.0f}s")
            return True
        
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
        
        # Heartbeat log every 60s for log aggregation systems
        if elapsed % 60 < poll_interval:
            logger.info(
                f"Still waiting for transcript: {asset_id} "
                f"(elapsed={elapsed:.0f}s / timeout={timeout:.0f}s)"
            )
    
    logger.warning(f"Transcript timeout for {asset_id} after {timeout:.0f}s")
    return False
