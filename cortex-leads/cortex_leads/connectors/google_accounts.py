"""Google sign-ins made in the console (WP37). The browser flow is the loopback one of `google_auth` moved to the server: the console sends the
person to Google, Google sends them back to `/api/v1/google/callback` with a code, and the refresh token is stored once as a `google_account`.
`state` is a Fernet token (tenant, who started it, PKCE verifier, the label, the permissions asked for) that expires in ten minutes, so the
callback needs no session (the cookie is SameSite=Strict and is not sent on the redirect back from Google) and cannot be forged."""
import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from cryptography.fernet import Fernet, InvalidToken

from cortex_leads.config import get_settings
from cortex_leads.connectors import classroom
from cortex_leads.connectors.google_auth import (
    RefreshToken,
    authorization_url,
    exchange_code,
    token_url,
)
from cortex_leads.core.errors import CortexError

STATE_TTL_S = 600
# What each thing needs from Google. Asked for separately, so a teacher who only wants recordings is never asked for Classroom.
KINDS = {"classroom": classroom.SCOPES, "classroom_post": classroom.POST_SCOPES, "classroom_create": classroom.COURSE_SCOPES, "drive": classroom.DRIVE_ONLY_SCOPES,
         "drive_read": ["https://www.googleapis.com/auth/drive.readonly"]}  # drive_read: watch a folder the teacher already has (Meet recordings), which `drive.file` cannot see
IDENTITY = ["openid", "email"]
CALLBACK_PATH = "/api/v1/google/callback"


class GoogleSetupError(CortexError):
    """`.code`: NOT_CONFIGURED (no OAuth client or no public address on this server) | BAD_STATE | NO_REFRESH_TOKEN | EXCHANGE_FAILED | TOKEN_REFUSED (Google would not issue an access token: the sign-in was revoked or Google did not answer)"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Pending:
    tenant_id: UUID
    actor: str
    label: str
    kinds: list[str]
    verifier: str
    reconnect: UUID | None = None  # set: this sign-in replaces the secret of that existing account instead of making a new one


def _fernet() -> Fernet:
    return Fernet(get_settings().CONNECTOR_SECRET_KEY)


def client() -> tuple[str, str, str]:
    """(client id, secret, redirect uri) of this deployment, or GoogleSetupError("NOT_CONFIGURED")."""
    s = get_settings()
    if not (s.GOOGLE_OAUTH_CLIENT_ID and s.GOOGLE_OAUTH_CLIENT_SECRET and s.PUBLIC_BASE_URL):
        raise GoogleSetupError("NOT_CONFIGURED")
    base = urlsplit(s.PUBLIC_BASE_URL)  # the address of the site only: a path on it (".../app") is not where the API lives
    return s.GOOGLE_OAUTH_CLIENT_ID, s.GOOGLE_OAUTH_CLIENT_SECRET, f"{base.scheme}://{base.netloc}{CALLBACK_PATH}"


def scopes_for(kinds: list[str]) -> list[str]:
    optional = classroom.TOPIC_SCOPES if "classroom" in kinds else []
    return IDENTITY + [x for k in kinds for x in KINDS[k]] + optional


def begin(tenant_id: UUID, actor: str, label: str, kinds: list[str], reconnect: UUID | None = None) -> str:
    """The address to send the person to."""
    client_id, _, redirect = client()
    verifier = secrets.token_urlsafe(48)
    state = _fernet().encrypt(json.dumps({"t": str(tenant_id), "a": actor, "l": label, "k": kinds, "v": verifier, "r": str(reconnect) if reconnect else None}).encode()).decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return authorization_url(client_id, redirect, scopes_for(kinds), state, challenge)


def read_state(state: str) -> Pending:
    try:
        d = json.loads(_fernet().decrypt(state.encode(), ttl=STATE_TTL_S))
        return Pending(UUID(d["t"]), d["a"], d["l"], list(d["k"]), d["v"], UUID(d["r"]) if d.get("r") else None)
    except (InvalidToken, ValueError, KeyError):
        raise GoogleSetupError("BAD_STATE") from None


@dataclass(frozen=True)
class Signed:
    secret: bytes  # {client_id, client_secret, refresh_token}, for Fernet
    scopes: list[str]  # short names, as Google reports them
    email: str | None


def _email_of(id_token: str | None) -> str | None:
    """From the id token Google handed us over TLS in the same answer as the refresh token, so it is read, not verified."""
    try:
        body = (id_token or "").split(".")[1]
        return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))).get("email")
    except (IndexError, ValueError):
        return None


def new_http() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=20)  # looked up at call time, so a test can stand a fake Google in its place


async def finish(pending: Pending, code: str) -> Signed:
    """Trades the code Google sent back for the refresh token. The HTTP client is made here: no other package imports a network library."""
    client_id, client_secret, redirect = client()
    try:
        async with new_http() as http:
            tokens = await exchange_code(http, client_id, client_secret, code, redirect, pending.verifier)
    except httpx.HTTPError:
        raise GoogleSetupError("EXCHANGE_FAILED") from None
    if not tokens.get("refresh_token"):
        raise GoogleSetupError("NO_REFRESH_TOKEN")
    granted = [x.rsplit("/", 1)[-1] for x in tokens.get("scope", "").split()]
    return Signed(json.dumps({"client_id": client_id, "client_secret": client_secret, "refresh_token": tokens["refresh_token"]}).encode(),
                  granted, _email_of(tokens.get("id_token")))


def missing_for(kind: str, granted: list[str]) -> list[str]:
    """Permissions `kind` needs that the account was not given (short names); empty: it can serve."""
    return [x.rsplit("/", 1)[-1] for x in KINDS[kind] if x.rsplit("/", 1)[-1] not in granted]


def account_secret(account) -> bytes:  # type: ignore[no-untyped-def]
    """The decrypted {client_id, client_secret, refresh_token} of a Google account."""
    return _fernet().decrypt(account.secret_enc)


def secret_of(row, unavailable: CortexError) -> bytes:  # type: ignore[no-untyped-def]
    """The decrypted sign-in of a Classroom source, Drive target or watched folder: its Google account's, the only kind there is. A source with
    no account (made before WP37 with a key of its own) or with a revoked one raises `unavailable`, the error the caller already handles for an
    expired sign-in, and the person is told to connect an account."""
    return secret_of_account(row.account, unavailable)


def secret_of_account(account, unavailable: CortexError) -> bytes:  # type: ignore[no-untyped-def]
    """Same, for a row that names its Google account itself (a class has two: the one that reads Drive and the one that acts in Classroom)."""
    if account is None or account.status != "active":
        raise unavailable
    return account_secret(account)


async def revoke_at_google(secret: bytes) -> None:
    """Tell Google to forget the token. Best effort: the account is revoked here either way."""
    try:
        async with new_http() as http:
            await http.post(token_url().replace("/token", "/revoke"), data={"token": json.loads(secret)["refresh_token"]})
    except httpx.HTTPError:
        pass


async def short_lived_token(secret: bytes, scope: str) -> tuple[str, int]:
    """A fresh access token narrowed to `scope`, and its lifetime in seconds: the one thing of a sign-in that may leave the server (WP44, the
    Drive picker needs it in the browser). The refresh token never does. Raises GoogleSetupError(TOKEN_REFUSED)."""
    data = json.loads(secret)
    http = new_http()
    try:
        return await RefreshToken(data["client_id"], data["client_secret"], data["refresh_token"], http, scope=scope).fresh()
    except httpx.HTTPError:
        raise GoogleSetupError("TOKEN_REFUSED") from None
    finally:
        await http.aclose()
