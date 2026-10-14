"""Skill manifest: the frontmatter of SKILL.md (DESIGN §5.8)."""
import re
from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

_DURATION = re.compile(r"^(\d+)([smhd])$")


def parse_duration(text: str) -> timedelta:
    """The one duration parser: "30s", "5m", "20h", "2d". A bad shape is a lint error, not a runtime one."""
    if not isinstance(text, str) or not (mt := _DURATION.match(text)) or int(mt[1]) == 0:
        raise ValueError(f"bad duration {text!r} (use 30s, 5m, 20h or 2d)")
    return timedelta(**{{"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[mt[2]]: int(mt[1])})


class Trigger(BaseModel):
    kind: Literal["relative", "event"]
    on: str
    # Values stay `Any` so lint can report a bad shape instead of pydantic hiding it.
    match: dict[str, Any] = {}
    after: str | None = None


class SendPolicy(BaseModel):
    """Blocking layer 1 (DESIGN A9, §5.8). Absent = follow `sandbox.send_mode`."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["auto", "manual"]
    auto_when: dict[str, Any] = {}  # may only tighten the floor: window: free, max_per_contact_per_day
    fallback: Literal["manual"] = "manual"


class SkillManifest(BaseModel):
    # extra="allow": unknown keys survive parsing so lint can count/report them.
    model_config = ConfigDict(extra="allow")

    name: str
    description: str
    version: int
    status: Literal["draft", "shadow", "live"] = "draft"
    trigger: Trigger
    requires_tools: list[str] = []
    output_kind: str
    limits: dict[str, Any] = {}
    must_handoff: list[str] = []
    never_say: list[str] = []
    approval: str = "always"
    send_policy: SendPolicy | None = None
    handoff_reply: str | None = None  # turn skill: honest holding line sent while a person takes over
    eval: dict[str, Any] | None = None

    def field_count(self) -> int:
        return len(self.model_fields_set) + len(self.model_extra or {})
