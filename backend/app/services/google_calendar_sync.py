from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import logging
from urllib.parse import quote

import httpx
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    CalendarConnection,
    CalendarProvider,
    Schedule,
    ScheduleExternalMap,
    SyncSource,
)

logger = logging.getLogger(__name__)


class GoogleCalendarSyncService:
    """One-way sync from internal schedules to Google Calendar events."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def sync_upsert_schedule(self, schedule: Schedule) -> None:
        connection = self._get_connection(schedule.user_id)
        if connection is None:
            return

        try:
            access_token = self.ensure_access_token(connection)
            mapping = self.db.query(ScheduleExternalMap).filter(
                ScheduleExternalMap.schedule_id == schedule.id,
                ScheduleExternalMap.provider == CalendarProvider.GOOGLE,
            ).first()

            if mapping is None:
                payload = self._build_event_payload(schedule)
                event = self._create_event(connection.provider_calendar_id, access_token, payload)
                self.db.add(ScheduleExternalMap(
                    user_id=schedule.user_id,
                    schedule_id=schedule.id,
                    provider=CalendarProvider.GOOGLE,
                    provider_calendar_id=connection.provider_calendar_id,
                    provider_event_id=event["id"],
                    provider_etag=event.get("etag"),
                    provider_updated_at=self._parse_google_updated(event.get("updated")),
                    last_sync_source=SyncSource.INTERNAL,
                    last_synced_at=datetime.utcnow(),
                    is_deleted_remote=False,
                ))
            else:
                payload = self._build_event_payload(schedule)
                try:
                    event = self._patch_event(
                        mapping.provider_calendar_id,
                        mapping.provider_event_id,
                        access_token,
                        payload,
                    )
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 404:
                        event = self._create_event(connection.provider_calendar_id, access_token, payload)
                        mapping.provider_calendar_id = connection.provider_calendar_id
                        mapping.provider_event_id = event["id"]
                    else:
                        raise
                mapping.provider_etag = event.get("etag")
                mapping.provider_updated_at = self._parse_google_updated(event.get("updated"))
                mapping.last_sync_source = SyncSource.INTERNAL
                mapping.last_synced_at = datetime.utcnow()
                mapping.is_deleted_remote = False
                self.db.add(mapping)

            connection.last_sync_error = None
            connection.last_synced_at = datetime.utcnow()
            self.db.add(connection)
            self.db.commit()
        except Exception as exc:
            logger.exception("Failed to sync schedule %s to Google Calendar", schedule.id)
            connection.last_sync_error = str(exc)
            self.db.add(connection)
            self.db.commit()

    def sync_delete_schedule(self, schedule: Schedule) -> None:
        connection = self._get_connection(schedule.user_id)
        if connection is None:
            return

        mapping = self.db.query(ScheduleExternalMap).filter(
            ScheduleExternalMap.schedule_id == schedule.id,
            ScheduleExternalMap.provider == CalendarProvider.GOOGLE,
        ).first()

        if mapping is None:
            return

        try:
            access_token = self.ensure_access_token(connection)
            self._delete_event(
                calendar_id=mapping.provider_calendar_id,
                event_id=mapping.provider_event_id,
                access_token=access_token,
            )
            connection.last_sync_error = None
            connection.last_synced_at = datetime.utcnow()
            self.db.add(connection)
        except Exception as exc:
            logger.exception("Failed to delete Google Calendar event for schedule %s", schedule.id)
            connection.last_sync_error = str(exc)
            self.db.add(connection)
        finally:
            self.db.delete(mapping)
            self.db.commit()

    def _get_connection(self, user_id) -> CalendarConnection | None:
        return self.db.query(CalendarConnection).filter(
            CalendarConnection.user_id == user_id,
            CalendarConnection.provider == CalendarProvider.GOOGLE,
            CalendarConnection.provider_calendar_id == settings.GOOGLE_CALENDAR_DEFAULT_ID,
        ).first()

    def ensure_access_token(self, connection: CalendarConnection) -> str:
        now = datetime.utcnow()
        if connection.access_token_encrypted and connection.access_token_expires_at and connection.access_token_expires_at > now + timedelta(minutes=2):
            return self._decrypt_token(connection.access_token_encrypted)

        refresh_token = self._decrypt_token(connection.refresh_token_encrypted)
        payload = {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }

        with httpx.Client(timeout=20) as client:
            response = client.post(settings.GOOGLE_OAUTH_TOKEN_URL, data=payload)
            response.raise_for_status()

        data = response.json()
        access_token = data.get("access_token")
        if not access_token:
            raise RuntimeError("Google token refresh response missing access_token")

        expires_in = data.get("expires_in", 3600)
        connection.access_token_encrypted = self._encrypt_token(access_token)
        connection.access_token_expires_at = now + timedelta(seconds=int(expires_in))
        self.db.add(connection)
        self.db.commit()
        return access_token

    def _event_headers(self, access_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    def _create_event(self, calendar_id: str, access_token: str, payload: dict) -> dict:
        encoded_calendar_id = quote(calendar_id, safe="")
        url = f"{settings.GOOGLE_CALENDAR_API_BASE_URL}/calendars/{encoded_calendar_id}/events"
        with httpx.Client(timeout=20) as client:
            response = client.post(url, headers=self._event_headers(access_token), json=payload)
            response.raise_for_status()
        return response.json()

    def _patch_event(self, calendar_id: str, event_id: str, access_token: str, payload: dict) -> dict:
        encoded_calendar_id = quote(calendar_id, safe="")
        encoded_event_id = quote(event_id, safe="")
        url = f"{settings.GOOGLE_CALENDAR_API_BASE_URL}/calendars/{encoded_calendar_id}/events/{encoded_event_id}"
        with httpx.Client(timeout=20) as client:
            response = client.patch(url, headers=self._event_headers(access_token), json=payload)
            response.raise_for_status()
        return response.json()

    def _delete_event(self, calendar_id: str, event_id: str, access_token: str) -> None:
        encoded_calendar_id = quote(calendar_id, safe="")
        encoded_event_id = quote(event_id, safe="")
        url = f"{settings.GOOGLE_CALENDAR_API_BASE_URL}/calendars/{encoded_calendar_id}/events/{encoded_event_id}"
        with httpx.Client(timeout=20) as client:
            response = client.delete(url, headers=self._event_headers(access_token))
            if response.status_code not in {200, 204, 404}:
                response.raise_for_status()

    def _build_event_payload(self, schedule: Schedule) -> dict:
        return {
            "summary": schedule.title,
            "description": schedule.description or "",
            "location": schedule.location or "",
            "start": {
                "dateTime": self._to_rfc3339_utc(schedule.start_time),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": self._to_rfc3339_utc(schedule.end_time),
                "timeZone": "UTC",
            },
            "extendedProperties": {
                "private": {
                    "cortexScheduleId": str(schedule.id),
                    "cortexType": str(schedule.type.value if hasattr(schedule.type, 'value') else schedule.type),
                }
            },
        }

    def _to_rfc3339_utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat().replace("+00:00", "Z")

    def _parse_google_updated(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            normalized = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            return None

    def _token_cipher(self) -> Fernet:
        explicit_key = settings.EXTERNAL_TOKEN_ENCRYPTION_KEY.strip()
        if explicit_key:
            key = explicit_key.encode("utf-8")
        else:
            derived = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
            key = base64.urlsafe_b64encode(derived)
        return Fernet(key)

    def _encrypt_token(self, value: str) -> str:
        return self._token_cipher().encrypt(value.encode("utf-8")).decode("utf-8")

    def _decrypt_token(self, value: str) -> str:
        return self._token_cipher().decrypt(value.encode("utf-8")).decode("utf-8")
