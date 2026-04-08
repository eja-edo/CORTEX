from datetime import datetime, timedelta, timezone
import base64
import hashlib
import secrets
import uuid
from urllib.parse import quote, urlencode, urlparse, parse_qsl, urlunparse

import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_active_user
from app.models import CalendarConnection, CalendarProvider, OAuthState, Schedule, User
from app.schemas import GoogleCalendarConnectionStatus, GoogleConnectUrlResponse, MessageResponse
from app.services.google_calendar_sync import GoogleCalendarSyncService

router = APIRouter(prefix="/google-calendar", tags=["google-calendar"])


def _hash_state(raw_state: str) -> str:
    return hashlib.sha256(raw_state.encode("utf-8")).hexdigest()


def _token_cipher() -> Fernet:
    explicit_key = settings.EXTERNAL_TOKEN_ENCRYPTION_KEY.strip()
    if explicit_key:
        key = explicit_key.encode("utf-8")
    else:
        # Fallback keeps local dev usable without extra setup; production should use EXTERNAL_TOKEN_ENCRYPTION_KEY.
        derived = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(derived)
    return Fernet(key)


def _encrypt_token(value: str) -> str:
    return _token_cipher().encrypt(value.encode("utf-8")).decode("utf-8")


def _channel_token(connection: CalendarConnection, channel_id: str) -> str:
    seed = f"{settings.SECRET_KEY}:{connection.user_id}:{connection.provider_calendar_id}:{channel_id}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _to_utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _stop_channel_if_present(connection: CalendarConnection, access_token: str) -> None:
    if not connection.channel_id or not connection.channel_resource_id:
        return

    stop_url = f"{settings.GOOGLE_CALENDAR_API_BASE_URL}/channels/stop"
    payload = {
        "id": connection.channel_id,
        "resourceId": connection.channel_resource_id,
    }
    with httpx.Client(timeout=20) as client:
        response = client.post(
            stop_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if response.status_code not in {200, 204, 404}:
            response.raise_for_status()


def _watch_events(connection: CalendarConnection, access_token: str) -> None:
    if not settings.GOOGLE_CALENDAR_WEBHOOK_URL:
        raise HTTPException(status_code=500, detail="GOOGLE_CALENDAR_WEBHOOK_URL is not configured")

    now = datetime.utcnow()
    requested_expiration_ms = int((now + timedelta(seconds=settings.GOOGLE_CALENDAR_CHANNEL_TTL_SECONDS)).timestamp() * 1000)
    channel_id = str(uuid.uuid4())

    if connection.channel_id and connection.channel_resource_id:
        try:
            _stop_channel_if_present(connection, access_token)
        except httpx.HTTPError:
            # Continue with new watch channel even if old channel could not be stopped.
            pass

    token = _channel_token(connection, channel_id)
    encoded_calendar_id = quote(connection.provider_calendar_id, safe="")
    watch_url = f"{settings.GOOGLE_CALENDAR_API_BASE_URL}/calendars/{encoded_calendar_id}/events/watch"
    payload = {
        "id": channel_id,
        "type": "web_hook",
        "address": settings.GOOGLE_CALENDAR_WEBHOOK_URL,
        "token": token,
        "expiration": requested_expiration_ms,
    }

    with httpx.Client(timeout=20) as client:
        response = client.post(
            watch_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()

    watch_data = response.json()
    expiration_ms = watch_data.get("expiration")
    expiration_dt = None
    if expiration_ms:
        expiration_dt = _to_utc_naive(datetime.fromtimestamp(int(expiration_ms) / 1000, tz=timezone.utc))

    connection.channel_id = watch_data.get("id") or channel_id
    connection.channel_resource_id = watch_data.get("resourceId")
    connection.channel_expiration = expiration_dt
    connection.last_sync_error = None
    connection.updated_at = datetime.utcnow()


def _append_query(url: str, extra_params: dict[str, str]) -> str:
    parsed = urlparse(url)
    existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
    existing.update(extra_params)
    updated_query = urlencode(existing)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, updated_query, parsed.fragment))


@router.get("/connect-url", response_model=GoogleConnectUrlResponse)
def create_connect_url(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    if not settings.GOOGLE_OAUTH_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GOOGLE_OAUTH_CLIENT_ID is not configured")

    raw_state = secrets.token_urlsafe(48)
    expires_at = datetime.utcnow() + timedelta(seconds=settings.GOOGLE_OAUTH_STATE_TTL_SECONDS)

    db_state = OAuthState(
        user_id=current_user.id,
        provider=CalendarProvider.GOOGLE,
        state_hash=_hash_state(raw_state),
        expires_at=expires_at,
    )
    db.add(db_state)
    db.commit()

    params = {
        "response_type": "code",
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
        "scope": " ".join(settings.GOOGLE_CALENDAR_SCOPES),
        "state": raw_state,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
    }

    authorization_url = f"{settings.GOOGLE_OAUTH_AUTH_URL}?{urlencode(params)}"
    return {
        "authorization_url": authorization_url,
        "state": raw_state,
        "expires_in": settings.GOOGLE_OAUTH_STATE_TTL_SECONDS,
    }


@router.get("/status", response_model=GoogleCalendarConnectionStatus)
def get_connection_status(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    connection = db.query(CalendarConnection).filter(
        CalendarConnection.user_id == current_user.id,
        CalendarConnection.provider == CalendarProvider.GOOGLE,
    ).first()

    if not connection:
        return {
            "connected": False,
            "provider": CalendarProvider.GOOGLE.value,
            "calendar_id": None,
            "granted_scopes": [],
            "last_synced_at": None,
            "has_sync_token": False,
            "channel_expiration": None,
            "last_sync_error": None,
        }

    return {
        "connected": True,
        "provider": connection.provider.value,
        "calendar_id": connection.provider_calendar_id,
        "granted_scopes": connection.granted_scopes or [],
        "last_synced_at": connection.last_synced_at,
        "has_sync_token": bool(connection.sync_token),
        "channel_expiration": connection.channel_expiration,
        "last_sync_error": connection.last_sync_error,
    }


@router.delete("/disconnect", response_model=MessageResponse)
def disconnect_calendar(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    connection = db.query(CalendarConnection).filter(
        CalendarConnection.user_id == current_user.id,
        CalendarConnection.provider == CalendarProvider.GOOGLE,
    ).first()

    if connection:
        try:
            access_token = GoogleCalendarSyncService(db).ensure_access_token(connection)
            _stop_channel_if_present(connection, access_token)
        except Exception:
            # Keep disconnect best-effort for provider cleanup.
            pass
        db.delete(connection)
    db.commit()
    return {"message": "Google Calendar disconnected"}


@router.post("/sync-now", response_model=MessageResponse)
def sync_now(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    schedules = db.query(Schedule).filter(Schedule.user_id == current_user.id).all()
    service = GoogleCalendarSyncService(db)
    for schedule in schedules:
        service.sync_upsert_schedule(schedule)

    return {"message": f"Sync requested for {len(schedules)} schedules"}


@router.post("/watch/start", response_model=MessageResponse)
def start_watch(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    connection = db.query(CalendarConnection).filter(
        CalendarConnection.user_id == current_user.id,
        CalendarConnection.provider == CalendarProvider.GOOGLE,
        CalendarConnection.provider_calendar_id == settings.GOOGLE_CALENDAR_DEFAULT_ID,
    ).first()
    if not connection:
        raise HTTPException(status_code=400, detail="Google Calendar is not connected")

    access_token = GoogleCalendarSyncService(db).ensure_access_token(connection)
    _watch_events(connection, access_token)
    db.add(connection)
    db.commit()
    return {"message": "Google Calendar watch channel started"}


@router.post("/watch/renew", response_model=MessageResponse)
def renew_watch(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    connection = db.query(CalendarConnection).filter(
        CalendarConnection.user_id == current_user.id,
        CalendarConnection.provider == CalendarProvider.GOOGLE,
        CalendarConnection.provider_calendar_id == settings.GOOGLE_CALENDAR_DEFAULT_ID,
    ).first()
    if not connection:
        raise HTTPException(status_code=400, detail="Google Calendar is not connected")

    access_token = GoogleCalendarSyncService(db).ensure_access_token(connection)
    _watch_events(connection, access_token)
    db.add(connection)
    db.commit()
    return {"message": "Google Calendar watch channel renewed"}


@router.post("/watch/renew-due", response_model=MessageResponse)
def renew_due_watches(
    x_cron_key: str | None = Header(default=None, alias="X-Cron-Key"),
    db: Session = Depends(get_db),
):
    if settings.GOOGLE_CALENDAR_RENEW_CRON_KEY:
        if not x_cron_key or x_cron_key != settings.GOOGLE_CALENDAR_RENEW_CRON_KEY:
            raise HTTPException(status_code=401, detail="Invalid cron key")

    now = datetime.utcnow()
    threshold = now + timedelta(seconds=settings.GOOGLE_CALENDAR_CHANNEL_RENEW_BEFORE_SECONDS)
    due_connections = db.query(CalendarConnection).filter(
        CalendarConnection.provider == CalendarProvider.GOOGLE,
        CalendarConnection.channel_expiration.isnot(None),
        CalendarConnection.channel_expiration <= threshold,
    ).all()

    renewed = 0
    for connection in due_connections:
        try:
            access_token = GoogleCalendarSyncService(db).ensure_access_token(connection)
            _watch_events(connection, access_token)
            db.add(connection)
            renewed += 1
        except Exception as exc:
            connection.last_sync_error = str(exc)
            db.add(connection)

    db.commit()
    return {"message": f"Renewed {renewed} watch channel(s)"}


@router.post("/webhook", status_code=204)
def receive_push_notification(
    x_goog_channel_id: str | None = Header(default=None, alias="X-Goog-Channel-Id"),
    x_goog_resource_id: str | None = Header(default=None, alias="X-Goog-Resource-Id"),
    x_goog_channel_token: str | None = Header(default=None, alias="X-Goog-Channel-Token"),
    x_goog_resource_state: str | None = Header(default=None, alias="X-Goog-Resource-State"),
    db: Session = Depends(get_db),
):
    if not x_goog_channel_id:
        return None

    connection = db.query(CalendarConnection).filter(
        CalendarConnection.provider == CalendarProvider.GOOGLE,
        CalendarConnection.channel_id == x_goog_channel_id,
    ).first()
    if not connection:
        return None

    expected_token = _channel_token(connection, x_goog_channel_id)
    if x_goog_channel_token and x_goog_channel_token != expected_token:
        raise HTTPException(status_code=401, detail="Invalid channel token")

    if connection.channel_resource_id and x_goog_resource_id and connection.channel_resource_id != x_goog_resource_id:
        raise HTTPException(status_code=401, detail="Invalid resource id")

    # Push payload has no body; schedule heavy work outside request path.
    if x_goog_resource_state in {"sync", "exists", "not_exists"}:
        connection.last_synced_at = datetime.utcnow()
        connection.last_sync_error = None
        db.add(connection)
        db.commit()

    return None


@router.get("/callback")
def google_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if error:
        redirect_url = _append_query(settings.GOOGLE_POST_CONNECT_REDIRECT_URL, {
            "google_calendar": "error",
            "reason": error,
        })
        return RedirectResponse(url=redirect_url, status_code=302)

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    state_hash = _hash_state(state)
    oauth_state = db.query(OAuthState).filter(
        OAuthState.provider == CalendarProvider.GOOGLE,
        OAuthState.state_hash == state_hash,
    ).first()

    if not oauth_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    if oauth_state.used_at is not None:
        raise HTTPException(status_code=400, detail="OAuth state already used")

    if oauth_state.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="OAuth state expired")

    if not settings.GOOGLE_OAUTH_CLIENT_ID or not settings.GOOGLE_OAUTH_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Google OAuth credentials are not configured")

    token_payload = {
        "code": code,
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
        "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
        "grant_type": "authorization_code",
    }

    try:
        with httpx.Client(timeout=15) as client:
            token_response = client.post(settings.GOOGLE_OAUTH_TOKEN_URL, data=token_payload)
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Failed to reach Google OAuth token endpoint")

    if token_response.status_code >= 400:
        raise HTTPException(status_code=400, detail="Google token exchange failed")

    token_data = token_response.json()
    refresh_token = token_data.get("refresh_token")
    access_token = token_data.get("access_token")
    expires_in = token_data.get("expires_in")

    if not refresh_token:
        raise HTTPException(status_code=400, detail="Refresh token not returned by Google")

    if not access_token:
        raise HTTPException(status_code=400, detail="Access token not returned by Google")

    scope_value = token_data.get("scope", "")
    granted_scopes = [s for s in scope_value.split(" ") if s] if scope_value else settings.GOOGLE_CALENDAR_SCOPES

    connection = db.query(CalendarConnection).filter(
        CalendarConnection.user_id == oauth_state.user_id,
        CalendarConnection.provider == CalendarProvider.GOOGLE,
        CalendarConnection.provider_calendar_id == settings.GOOGLE_CALENDAR_DEFAULT_ID,
    ).first()

    expires_at = None
    if isinstance(expires_in, int):
        expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    if connection is None:
        connection = CalendarConnection(
            user_id=oauth_state.user_id,
            provider=CalendarProvider.GOOGLE,
            provider_calendar_id=settings.GOOGLE_CALENDAR_DEFAULT_ID,
            refresh_token_encrypted=_encrypt_token(refresh_token),
            access_token_encrypted=_encrypt_token(access_token),
            access_token_expires_at=expires_at,
            granted_scopes=granted_scopes,
        )
    else:
        connection.refresh_token_encrypted = _encrypt_token(refresh_token)
        connection.access_token_encrypted = _encrypt_token(access_token)
        connection.access_token_expires_at = expires_at
        connection.granted_scopes = granted_scopes
        connection.last_sync_error = None

    oauth_state.used_at = datetime.utcnow()
    db.add(connection)
    db.add(oauth_state)
    db.commit()

    redirect_url = _append_query(settings.GOOGLE_POST_CONNECT_REDIRECT_URL, {
        "google_calendar": "connected",
    })
    return RedirectResponse(url=redirect_url, status_code=302)
