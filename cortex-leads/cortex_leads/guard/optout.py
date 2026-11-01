"""A customer asking us to stop writing (0 token, rules only). Unlike a guessed outcome, this one is acted on
at once without a person's confirmation: a wrong guess costs one silenced follow-up that staff can undo, a
missed one costs a message the customer told us not to send."""
import re

from cortex_leads.privacy.redact import _fold

_STOP = re.compile(
    r"\b(?:dung|ngung|thoi)\s+(?:nhan\s+tin|gui\s+tin|lien\s+he|lam\s+phien)\b"
    r"|\b(?:dung|ngung|thoi)\s+(?:nhan|gui|goi)\b.*\bnua\b"  # "đừng gọi giờ trưa" is a preference, "đừng gọi nữa" is not
    r"|\bkhong\s+(?:muon|can)\s+(?:duoc\s+)?nhan\s+(?:tin|thong\s+bao|quang\s+cao)\b"
    r"|\b(?:huy|bo|tat)\s+(?:dang\s+ky\s+)?nhan\s+(?:tin|thong\s+bao)\b"
    r"|\bunsubscribe\b|^\s*stop\s*[.!]*\s*$")


def wants_to_stop(text: str) -> bool:
    return _STOP.search(_fold(text)) is not None
