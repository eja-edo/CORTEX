"""How a call to a Google API proves who it is for (WP33). Two ways, one question: `headers()` gives the Authorization header.
A service account signs a short-lived JWT itself (with `subject`, it acts as that user, which needs the domain admin's
delegation); an OAuth client with a refresh token (a teacher consented once) exchanges it for an access token. Tokens are
kept until a minute before they expire."""
import base64
import os
import time
from typing import Protocol
from urllib.parse import urlencode

import httpx

EARLY_S = 60


DEFAULT_TOKEN_URL = "https://oauth2.googleapis.com/token"


def token_url() -> str:
    """Read straight from the environment (CL_GOOGLE_TOKEN_URL; the fake Classroom sets it), not from the full settings: signing a teacher in
    must work on a machine with no database and no keys configured."""
    return os.environ.get("CL_GOOGLE_TOKEN_URL") or DEFAULT_TOKEN_URL


class TokenSource(Protocol):
    async def headers(self) -> dict[str, str]: ...


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class _Cached:
    def __init__(self) -> None:
        self._token: tuple[str, float] | None = None

    async def _fresh(self) -> tuple[str, int]:
        raise NotImplementedError

    async def headers(self) -> dict[str, str]:
        if self._token is None or self._token[1] < time.time() + EARLY_S:
            token, ttl = await self._fresh()
            self._token = (token, time.time() + ttl)
        return {"Authorization": f"Bearer {self._token[0]}"}


class RefreshToken(_Cached):
    def __init__(self, client_id: str, client_secret: str, refresh_token: str, http: httpx.AsyncClient) -> None:
        super().__init__()
        self._form = {"grant_type": "refresh_token", "client_id": client_id, "client_secret": client_secret,
                      "refresh_token": refresh_token}
        self._http = http

    async def _fresh(self) -> tuple[str, int]:
        r = await self._http.post(token_url(), data=self._form)
        r.raise_for_status()
        return r.json()["access_token"], int(r.json().get("expires_in", 3600))


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"

def authorization_url(client_id: str, redirect_uri: str, scopes: list[str], state: str, challenge: str) -> str:
    """Where the teacher signs in and agrees. `prompt=select_account consent` shows the account chooser (so the right teacher is picked, not whichever is open) and `access_type=offline` + `consent` is what makes Google hand back a refresh token."""
    return AUTH_URL + "?" + urlencode({"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": " ".join(scopes),
                                       "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
                                       "access_type": "offline", "prompt": "select_account consent"})


async def exchange_code(http: httpx.AsyncClient, client_id: str, client_secret: str, code: str, redirect_uri: str, verifier: str) -> dict:
    r = await http.post(token_url(), data={"grant_type": "authorization_code", "code": code, "client_id": client_id,
                                                               "client_secret": client_secret, "redirect_uri": redirect_uri, "code_verifier": verifier})
    r.raise_for_status()
    return r.json()
