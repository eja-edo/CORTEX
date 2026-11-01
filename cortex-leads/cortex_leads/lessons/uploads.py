"""Recordings uploaded in the console (WP35, WP37): what may be sent and what it may be called. The bytes go from the browser straight
to Drive; this module only judges the request that opens that upload."""
import re
from pathlib import Path

from cortex_leads.config import get_settings
from cortex_leads.connectors.lesson_sources import MEDIA_SUFFIXES
from cortex_leads.core.errors import CortexError

MEDIA_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".mkv": "video/x-matroska", ".mp3": "audio/mpeg",
               ".m4a": "audio/mp4", ".wav": "audio/wav", ".ogg": "audio/ogg"}
LANGUAGES = {"vi", "en", "auto"}
MAX_NAME = 200


class UploadRefused(CortexError):
    """`.code`: TOO_LARGE | BAD_TYPE | EMPTY"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def max_bytes() -> int:
    return get_settings().UPLOAD_MAX_MB * 1024 * 1024


def suffix_of(name: str) -> str:
    suffix = Path(name.lower()).suffix
    if suffix not in MEDIA_SUFFIXES:
        raise UploadRefused("BAD_TYPE")
    return suffix


def clean_name(raw: str) -> str:
    """A label for the list: the last part of what the browser sent, no control characters, not absurdly long."""
    name = re.sub(r"[\x00-\x1f\x7f]", "", raw.replace("\\", "/").rsplit("/", 1)[-1]).strip()
    return name[:MAX_NAME] or "bản ghi"
