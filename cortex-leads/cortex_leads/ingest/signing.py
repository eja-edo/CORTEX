"""HMAC signing of ingest requests. Bridges (WP6) must call this same `sign`."""
import hashlib
import hmac
from datetime import datetime


def sign(secret: bytes, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret, str(timestamp).encode() + b"." + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def verify(secret: bytes, timestamp: int, body: bytes, signature: str,
           *, now: datetime, max_skew_s: int) -> bool:
    if abs(now.timestamp() - timestamp) > max_skew_s:  # replay protection
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), signature)
