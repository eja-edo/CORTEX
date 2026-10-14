import base64
import os
import time
from uuid import UUID


def uuid7() -> UUID:
    """RFC 9562 UUIDv7: 48-bit unix ms + random; time-ordered so indexes stay hot."""
    ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= ((rand >> 62) & 0xFFF) << 64
    value |= 0b10 << 62
    value |= rand & ((1 << 62) - 1)
    return UUID(int=value)


def new_connector_id() -> str:
    return "conn_" + base64.b32encode(os.urandom(10)).decode().lower().rstrip("=")
