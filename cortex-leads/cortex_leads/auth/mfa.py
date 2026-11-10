"""Two-step sign-in: a 6-digit code from an authenticator app (TOTP, RFC 6238) or one of ten recovery codes.

Each person turns it on for themselves (it is never required). The owner may turn it off for a staff member or teacher who lost their phone;
the person then signs in with the password alone and sets it up again on their own screen, so a secret is never shown to anyone else. An owner
who lost both phone and codes is reset by the operator (`cli reset-mfa`).

TOTP is written here with the standard library, as scrypt is: HMAC-SHA1, 6 digits, 30-second steps, one step of clock drift either way. A code
is accepted once: the step it matched is kept and an earlier or equal step is refused, so a code read over a shoulder cannot be replayed.

Between the password and the code there is no sign-in yet: the password step leaves a short-lived signed cookie (`cl_mfa`, 5 minutes) that
names the person and the version of their account, and only the code step makes the session."""
import base64
import hashlib
import hmac
import secrets
import struct
from datetime import UTC, datetime, timedelta
from urllib.parse import quote
from uuid import UUID

import jwt
from cryptography.fernet import Fernet, InvalidToken

from cortex_leads.config import get_settings

STEP = 30
DIGITS = 6
DRIFT = 1  # steps accepted either side of now: a phone a little fast or slow still works
RECOVERY_COUNT = 10
CHALLENGE_COOKIE = "cl_mfa"
CHALLENGE_PATH = "/api/v1/session"
CHALLENGE_TTL = timedelta(minutes=5)
ISSUER = "Cortex"


# --- TOTP ----------------------------------------------------------------------------------------------------------------------------------
def new_secret() -> str:
    """160 random bits, base32 without padding: what an authenticator app reads from the QR code."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    return base64.b32decode(secret + "=" * (-len(secret) % 8))


def code_at(secret: str, step: int) -> str:
    mac = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def step_of(now: datetime) -> int:
    return int(now.timestamp()) // STEP


def match(secret: str, code: str, now: datetime, last_step: int | None) -> int | None:
    """The step this code belongs to, or None. A step at or before `last_step` was already used and does not count again."""
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    here = step_of(now)
    for step in range(here - DRIFT, here + DRIFT + 1):
        if (last_step is None or step > last_step) and hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def otpauth_uri(secret: str, account: str) -> str:
    """What the QR code holds. The app shows «Cortex (email)»."""
    label = quote(f"{ISSUER}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}&algorithm=SHA1&digits={DIGITS}&period={STEP}"


# --- recovery codes ------------------------------------------------------------------------------------------------------------------------
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i: read off paper without guessing


def _plain(code: str) -> str:
    return code.strip().lower().replace("-", "").replace(" ", "")


def recovery_hash(code: str) -> str:
    return hashlib.sha256(b"mfa-recovery|" + _plain(code).encode()).hexdigest()


def new_recovery_codes() -> tuple[list[str], list[str]]:
    """Ten codes of ten characters (about 50 bits each), shown once, and the hashes that are kept."""
    codes = []
    for _ in range(RECOVERY_COUNT):
        raw = "".join(secrets.choice(_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes, [recovery_hash(c) for c in codes]


def looks_like_recovery(code: str) -> bool:
    return len(_plain(code)) == 10


# --- the secret at rest --------------------------------------------------------------------------------------------------------------------
def _fernet() -> Fernet:
    return Fernet(get_settings().CONNECTOR_SECRET_KEY)


def seal(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def unseal(sealed: str | None) -> str | None:
    """None when there is nothing, or when the server key changed since (then the person must set it up again)."""
    if not sealed:
        return None
    try:
        return _fernet().decrypt(sealed.encode()).decode()
    except InvalidToken:
        return None


def use_code(user, code: str, now: datetime) -> str | None:
    """Checks a code against the person's TOTP secret, then against their recovery codes, and spends it: the TOTP step is kept so the same
    code fails next time, a recovery code is struck off. Returns "totp", "recovery" or None. The caller holds the row locked."""
    secret = unseal(user.mfa_secret_enc)  # None when the server key changed: the recovery codes (hashes, no key) still work
    if secret is not None and (step := match(secret, code, now, user.mfa_last_step)) is not None:
        user.mfa_last_step = step
        return "totp"
    if looks_like_recovery(code):
        h = recovery_hash(code)
        if h in (user.mfa_recovery or []):
            user.mfa_recovery = [x for x in user.mfa_recovery if x != h]
            return "recovery"
    return None


def turn_off(user) -> None:
    user.mfa_secret_enc = user.mfa_pending_enc = None
    user.mfa_enabled_at = user.mfa_last_step = None
    user.mfa_recovery = None


# --- between the password and the code -----------------------------------------------------------------------------------------------------
def _challenge_key() -> bytes:
    cfg = get_settings()
    return hashlib.sha256(b"console-mfa|" + (cfg.JWT_SECRET or cfg.CONNECTOR_SECRET_KEY).encode()).digest()


def challenge(user_id: UUID, tenant_id: UUID, version: int, now: datetime) -> str:
    return jwt.encode({"sub": str(user_id), "tid": str(tenant_id), "ver": version, "aud": "mfa", "iat": int(now.timestamp()),
                       "exp": int((now + CHALLENGE_TTL).timestamp())}, _challenge_key(), algorithm="HS256")


def read_challenge(token: str | None, now: datetime | None = None) -> tuple[UUID, UUID, int] | None:
    if not token:
        return None
    try:
        c = jwt.decode(token, _challenge_key(), algorithms=["HS256"], audience="mfa",
                       options={"require": ["sub", "tid", "ver", "exp"]}, leeway=0)
    except jwt.PyJWTError:
        return None
    if now is not None and c["exp"] <= int(now.timestamp()):
        return None
    try:
        return UUID(c["sub"]), UUID(c["tid"]), int(c["ver"])
    except (ValueError, TypeError):
        return None


def throttle_key(user_id: UUID) -> str:
    """Wrong codes count here, at sign-in and in the account page alike."""
    return "mfa:" + hashlib.sha256(str(user_id).encode()).hexdigest()[:32]


def now() -> datetime:
    return datetime.now(UTC)
