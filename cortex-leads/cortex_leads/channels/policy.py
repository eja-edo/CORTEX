"""Channel window rules, computed by the core from channel.kind (DESIGN §5.2, §6)."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypedDict


@dataclass(frozen=True)
class ChannelPolicy:
    kind: str
    free_window_h: int  # window for any message after the customer's last one; 0 = never open
    human_agent_window_h: int | None = None  # extended window, for a human typing only
    verified: bool = True  # False = taken from unofficial sources (DESIGN §6)


CHANNEL_POLICIES: dict[str, ChannelPolicy] = {
    "messenger": ChannelPolicy("messenger", 24, 168),
    "zalo_oa": ChannelPolicy("zalo_oa", 48, None, verified=False),  # DESIGN §6: chưa xác minh
    "web": ChannelPolicy("web", 0),
}


class WindowState(TypedDict):
    open: bool
    basis: str | None  # "free" | "human_agent" | None
    expires_at: datetime | None


def window_state(channel_kind: str, last_customer_at: datetime | None, now: datetime) -> WindowState:
    """`basis == "human_agent"` means only a human may write; callers must not treat it as free."""
    policy = CHANNEL_POLICIES.get(channel_kind)
    if policy is None or last_customer_at is None or policy.free_window_h <= 0:
        return {"open": False, "basis": None, "expires_at": None}
    free_end = last_customer_at + timedelta(hours=policy.free_window_h)
    if now < free_end:
        return {"open": True, "basis": "free", "expires_at": free_end}
    if policy.human_agent_window_h:
        ha_end = last_customer_at + timedelta(hours=policy.human_agent_window_h)
        if now < ha_end:
            return {"open": True, "basis": "human_agent", "expires_at": ha_end}
        return {"open": False, "basis": None, "expires_at": ha_end}
    return {"open": False, "basis": None, "expires_at": free_end}
