import logging
import os
import sys

LOG_LEVEL_NAME = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_NAME, logging.INFO)
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_is_configured = False


def _configure_root_logger() -> None:
    global _is_configured
    if _is_configured:
        return

    logging.basicConfig(
        level=LOG_LEVEL,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        stream=sys.stdout,
    )

    # Suppress noisy dependencies.
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    _is_configured = True

def setup_logger(name: str) -> logging.Logger:
    """Setup logging configuration for a new logger"""
    _configure_root_logger()
    logger = logging.getLogger(name)
    logger.setLevel(LOG_LEVEL)
    return logger

# Set up base logger 
logger = setup_logger(__name__)


def get_logger(name: str) -> logging.Logger:
    """Get logger with consistent formatting"""
    return setup_logger(name)