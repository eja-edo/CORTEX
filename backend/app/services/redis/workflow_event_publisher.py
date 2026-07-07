"""
Publish events to the cortex:workflow:events Redis channel.

Workflow service's internal_event_listener subscribes to this channel
to trigger workflows matching the event type.
"""
import json
import redis
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

REDIS_CHANNEL = "cortex:workflow:events"


def publish_workflow_event(event_type: str, **data) -> bool:
    """
    Publish an event to the workflow events channel.

    Args:
        event_type: e.g. "schedule.created", "note.updated", "schedule.completed"
        data: key-value pairs to include in the event payload
    Returns:
        True if published successfully
    """
    try:
        r = redis.Redis.from_url(settings.REDIS_URL)
        payload = {"event": event_type, **data}
        r.publish(REDIS_CHANNEL, json.dumps(payload))
        r.close()
        logger.debug(f"Published workflow event: {event_type}")
        return True
    except Exception as e:
        logger.error(f"Failed to publish workflow event {event_type}: {e}")
        return False
