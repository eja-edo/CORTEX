import logging
import os
import sys

LOG_LEVEL_NAME = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_NAME, logging.INFO)
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_is_configured = False


class _UTF8StreamHandler(logging.StreamHandler):
    """StreamHandler that always encodes to UTF-8, regardless of system encoding."""
    def __init__(self, stream=None):
        super().__init__(stream)
        if stream is not None:
            try:
                self.stream = open(stream.name, 'a', encoding='utf-8', errors='replace')
            except Exception:
                pass


def _configure_root_logger() -> None:
    global _is_configured
    if _is_configured:
        return

    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        else:
            sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', errors='replace', closefd=False)
    except Exception:
        pass

    logging.basicConfig(
        level=LOG_LEVEL,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        stream=sys.stdout,
    )

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