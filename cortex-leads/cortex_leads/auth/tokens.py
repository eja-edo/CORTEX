"""The access token: a signed JWT in an HttpOnly cookie, short-lived (`ACCESS_TOKEN_MINUTES`). It says who (sub), which sign-in (sid), at which
version (ver), and carries what the console needs to answer a request without reading the database: the business, the role, the names. Details that
change (a role, a status, an email) bump the person's version, which kills the token; details that do not matter to safety (a display name, the
business name) are picked up whenever the refresh token is used for a new one, so they are never more than one access lifetime old.

HS256 with a key derived from the server's secret; `alg` is pinned on decode, so `none` and key-confusion tricks have nothing to land on.
`exp` is when this access token ends and `ac` is when the sign-in began (no token outlives `SESSION_ABSOLUTE_HOURS` from it)."""
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt

from cortex_leads.config import get_settings
from cortex_leads.db import models as m

ALG = "HS256"
ISS = "cortex-leads"


def _key() -> bytes:
    cfg = get_settings()
    return hashlib.sha256(b"console-jwt|" + (cfg.JWT_SECRET or cfg.CONNECTOR_SECRET_KEY).encode()).digest()


@dataclass(frozen=True)
class Claims:
    user_id: UUID
    sid: UUID
    version: int
    tenant_id: UUID
    role: str
    staff_ref: str
    email: str
    name: str
    tenant_name: str
    tz: str
    issued_at: datetime
    expires_at: datetime
    auth_time: datetime
    stale: bool = False  # set by `sessions.verify`: made at an older version, but this sign-in is still good, so it is to be given a fresh token


def expiry(auth_time: datetime, now: datetime) -> datetime:
    cfg = get_settings()
    return min(now + timedelta(minutes=cfg.ACCESS_TOKEN_MINUTES), auth_time + timedelta(hours=cfg.SESSION_ABSOLUTE_HOURS))


def issue(user: m.AppUser, tenant: m.Tenant, sid: UUID, auth_time: datetime, now: datetime) -> str:
    payload = {"iss": ISS, "sub": str(user.id), "sid": str(sid), "ver": user.token_version, "t": str(user.tenant_id), "r": user.role,
               "sr": user.staff_ref, "em": user.email, "nm": user.display_name, "tn": tenant.name, "tz": tenant.timezone,
               "iat": int(now.timestamp()), "exp": int(expiry(auth_time, now).timestamp()), "ac": int(auth_time.timestamp())}
    return jwt.encode(payload, _key(), algorithm=ALG)


def decode(token: str, now: datetime | None = None) -> Claims | None:
    """The claims of a token that is ours, unaltered and not past its time; None for anything else."""
    now = now or datetime.now(UTC)
    try:
        p = jwt.decode(token or "", _key(), algorithms=[ALG], issuer=ISS,
                       options={"require": ["exp", "iat", "sub", "sid", "ver", "t", "ac"], "verify_exp": False, "verify_iat": False})
        c = Claims(UUID(p["sub"]), UUID(p["sid"]), int(p["ver"]), UUID(p["t"]), str(p["r"]), str(p["sr"]), str(p["em"]), str(p["nm"]), str(p["tn"]),
                   str(p["tz"]), datetime.fromtimestamp(p["iat"], UTC), datetime.fromtimestamp(p["exp"], UTC), datetime.fromtimestamp(p["ac"], UTC))
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        return None
    cfg = get_settings()
    if c.expires_at <= now or c.auth_time + timedelta(hours=cfg.SESSION_ABSOLUTE_HOURS) <= now:
        return None
    return c
