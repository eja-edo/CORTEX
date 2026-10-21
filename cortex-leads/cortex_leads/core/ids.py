import base64
import os
import re
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


DEFAULT_CELL = "c1"  # the cell every id minted before cells existed belongs to
_CONNECTOR = re.compile(r"conn_(?:(?P<cell>[a-z][a-z0-9]{0,15})-)?[a-z2-7]+")


def new_connector_id(cell: str | None = None) -> str:
    """`conn_<random>` for the default cell, `conn_<cell>-<random>` for any other: a router can send a bridge's
    signed batch to the right cell from the id alone, without opening it or asking a database."""
    tag = f"{cell}-" if cell and cell != DEFAULT_CELL else ""
    return "conn_" + tag + base64.b32encode(os.urandom(10)).decode().lower().rstrip("=")


def cell_of(connector_id: str) -> str | None:
    """The cell a connector id belongs to; None when it is not shaped like one of ours."""
    mt = _CONNECTOR.fullmatch(connector_id or "")
    return None if mt is None else (mt["cell"] or DEFAULT_CELL)
