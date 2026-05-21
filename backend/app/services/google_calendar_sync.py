from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
from urllib.parse import quote
from uuid import UUID

import httpx
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    CalendarConnection,
    CalendarProvider,
    Schedule,
    ScheduleExternalMap,
    ScheduleType,
    SyncSource,
    ReminderStatus,
)
from app.services.recurrence import RecurrenceService
from app.utils.logger import get_logger

logger = get_logger(__name__)


class GoogleCalendarSyncService:
    """Bidirectional sync helpers for internal schedules and Google Calendar events."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def sync_upsert_schedule(self, schedule: Schedule) -> None:
        connection = self._get_connection(schedule.user_id)
        if connection is None:
            return

        connection_id = connection.id
        connection_user_id = connection.user_id

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
            self.db.rollback()
            logger.exception("Failed to sync schedule %s to Google Calendar", schedule.id)
            db_connection = self.db.query(CalendarConnection).filter(
                CalendarConnection.id == connection_id,
            ).first()
            if db_connection is not None:
                db_connection.last_sync_error = str(exc)
                self.db.add(db_connection)
                self.db.commit()
            else:
                logger.error("Calendar connection %s for user %s was not found while storing sync error", connection_id, connection_user_id)

    def sync_delete_schedule(self, schedule: Schedule) -> None:
        connection = self._get_connection(schedule.user_id)
        if connection is None:
            return

        connection_id = connection.id
        connection_user_id = connection.user_id

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
            self.db.rollback()
            logger.exception("Failed to delete Google Calendar event for schedule %s", schedule.id)
            db_connection = self.db.query(CalendarConnection).filter(
                CalendarConnection.id == connection_id,
            ).first()
            if db_connection is not None:
                db_connection.last_sync_error = str(exc)
                self.db.add(db_connection)
            else:
                logger.error("Calendar connection %s for user %s was not found while storing sync error", connection_id, connection_user_id)
        finally:
            db_mapping = self.db.query(ScheduleExternalMap).filter(
                ScheduleExternalMap.id == mapping.id,
            ).first()
            if db_mapping is not None:
                self.db.delete(db_mapping)
            self.db.commit()

    def sync_from_google_incremental(self, user_id) -> dict[str, int]:
        connection = self._get_connection(user_id)
        if connection is None:
            return {"created": 0, "updated": 0, "deleted": 0, "skipped": 0}
        return self.sync_from_google_incremental_for_connection(connection)

    def sync_from_google_incremental_for_connection(self, connection: CalendarConnection) -> dict[str, int]:
        """Pull changed Google Calendar events using sync token and upsert internal schedules."""
        stats = {"created": 0, "updated": 0, "deleted": 0, "skipped": 0}
        connection_id = connection.id
        connection_user_id = connection.user_id
        try:
            access_token = self.ensure_access_token(connection)

            if connection.sync_token:
                params = {
                    "syncToken": connection.sync_token,
                    "showDeleted": "true",
                    "maxResults": str(settings.GOOGLE_CALENDAR_SYNC_MAX_RESULTS),
                }
            else:
                # Initial sync: DON'T use singleEvents=true
                # We need root events with RRULE, not expanded instances
                now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
                time_min = now_utc - timedelta(days=settings.GOOGLE_CALENDAR_INITIAL_SYNC_PAST_DAYS)
                time_max = now_utc + timedelta(days=settings.GOOGLE_CALENDAR_INITIAL_SYNC_FUTURE_DAYS)
                params = {
                    "timeMin": time_min.isoformat().replace("+00:00", "Z"),
                    "timeMax": time_max.isoformat().replace("+00:00", "Z"),
                    # "singleEvents": "true",  # ❌ REMOVED - we need root events with RRULE
                    "showDeleted": "true",
                    "maxResults": str(settings.GOOGLE_CALENDAR_SYNC_MAX_RESULTS),
                }

            try:
                sync_token = self._consume_google_events(connection, access_token, params, stats)
            except httpx.HTTPStatusError as exc:
                # Google returns 410 when sync token is invalid/stale. Fall back to full windowed sync.
                if exc.response.status_code != 410:
                    raise
                connection.sync_token = None
                now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
                full_params = {
                    "timeMin": (now_utc - timedelta(days=settings.GOOGLE_CALENDAR_INITIAL_SYNC_PAST_DAYS)).isoformat().replace("+00:00", "Z"),
                    "timeMax": (now_utc + timedelta(days=settings.GOOGLE_CALENDAR_INITIAL_SYNC_FUTURE_DAYS)).isoformat().replace("+00:00", "Z"),
                    # "singleEvents": "true",  # ❌ REMOVED - we need root events with RRULE
                    "showDeleted": "true",
                    "maxResults": str(settings.GOOGLE_CALENDAR_SYNC_MAX_RESULTS),
                }
                sync_token = self._consume_google_events(connection, access_token, full_params, stats)

            connection.sync_token = sync_token
            connection.last_synced_at = datetime.utcnow()
            connection.last_sync_error = None
            self.db.add(connection)
            self.db.commit()
            return stats
        except Exception as exc:
            self.db.rollback()
            logger.exception("Failed incremental sync from Google for user %s", connection_user_id)
            db_connection = self.db.query(CalendarConnection).filter(
                CalendarConnection.id == connection_id,
            ).first()
            if db_connection is not None:
                db_connection.last_sync_error = str(exc)
                self.db.add(db_connection)
                self.db.commit()
            else:
                logger.error("Calendar connection %s for user %s was not found while storing sync error", connection_id, connection_user_id)
            raise

    def _consume_google_events(
        self,
        connection: CalendarConnection,
        access_token: str,
        params: dict[str, str],
        stats: dict[str, int],
    ) -> str | None:
        encoded_calendar_id = quote(connection.provider_calendar_id, safe="")
        url = f"{settings.GOOGLE_CALENDAR_API_BASE_URL}/calendars/{encoded_calendar_id}/events"
        page_token = None
        next_sync_token = None

        while True:
            request_params = dict(params)
            if page_token:
                request_params["pageToken"] = page_token

            with httpx.Client(timeout=20) as client:
                response = client.get(url, headers=self._event_headers(access_token), params=request_params)
                response.raise_for_status()

            payload = response.json()
            for event in payload.get("items", []):
                self._apply_google_event(connection, event, stats)

            page_token = payload.get("nextPageToken")
            if not page_token:
                next_sync_token = payload.get("nextSyncToken")
                break

        return next_sync_token

    def _apply_google_event(self, connection: CalendarConnection, event: dict, stats: dict[str, int]) -> None:
        event_id = event.get("id")
        if not event_id:
            stats["skipped"] += 1
            return

        try:
            # Use savepoint to isolate each event - prevents one failing event from rolling back the entire batch
            with self.db.begin_nested():
                self._process_google_event(connection, event, stats)
        except Exception as e:
            logger.error(f"Failed to apply Google event {event_id}: {e}")
            stats["skipped"] += 1

    def _process_google_event(self, connection: CalendarConnection, event: dict, stats: dict[str, int]) -> None:
        event_id = event.get("id")
        # Skip individual instances of recurring events
        # We only process root events (which have recurrence RRULE)
        # Instances will be generated by RecurrenceService from the root event
        if event.get("recurringEventId"):
            # This is an instance, not the root event - skip it
            stats["skipped"] += 1
            return

        mapping = self._resolve_mapping_for_event(connection, event_id, event)

        if event.get("status") == "cancelled":
            self._apply_google_deleted_event(connection, mapping, event, stats)
            return

        parsed_start = self._parse_google_event_time(event.get("start"))
        parsed_end = self._parse_google_event_time(event.get("end"))
        if parsed_start is None or parsed_end is None:
            stats["skipped"] += 1
            return

        provider_updated_at = self._parse_google_updated(event.get("updated"))
        if mapping and mapping.provider_updated_at and provider_updated_at and provider_updated_at <= mapping.provider_updated_at:
            stats["skipped"] += 1
            return

        # Parse recurrence from Google
        recurrence_rule = None
        google_recurrence = event.get("recurrence", [])
        if google_recurrence:
            for r in google_recurrence:
                if r.startswith("RRULE:"):
                    recurrence_rule = RecurrenceService().parse_google_rrule(r)
                    break

        # Parse reminders from Google
        reminder_configs = []
        google_reminders = event.get("reminders", {})
        if not google_reminders.get("useDefault") and google_reminders.get("overrides"):
            for override in google_reminders["overrides"]:
                reminder_configs.append({
                    "minutes_before": override.get("minutes", 10),
                    "method": "push" if override.get("method") == "popup" else "email",
                })

        if mapping:
            schedule = self.db.query(Schedule).filter(
                Schedule.id == mapping.schedule_id,
                Schedule.user_id == connection.user_id,
            ).first()
            if schedule is None:
                schedule = self._create_schedule_from_google_event(
                    connection, event, parsed_start, parsed_end, recurrence_rule
                )
                mapping.schedule_id = schedule.id
                stats["created"] += 1
            else:
                self._update_schedule_from_google_event(
                    schedule, event, parsed_start, parsed_end, recurrence_rule
                )
                stats["updated"] += 1
        else:
            schedule = self._resolve_schedule_from_event(connection, event)
            if schedule is None:
                schedule = self._create_schedule_from_google_event(
                    connection, event, parsed_start, parsed_end, recurrence_rule
                )
                stats["created"] += 1
            else:
                self._update_schedule_from_google_event(
                    schedule, event, parsed_start, parsed_end, recurrence_rule
                )
                stats["updated"] += 1

            # FIX: Include provider_etag and provider_updated_at in constructor
            mapping = ScheduleExternalMap(
                user_id=connection.user_id,
                schedule_id=schedule.id,
                provider=CalendarProvider.GOOGLE,
                provider_calendar_id=connection.provider_calendar_id,
                provider_event_id=event_id,
                provider_etag=event.get("etag"),
                provider_updated_at=provider_updated_at,
                last_sync_source=SyncSource.PROVIDER,
                last_synced_at=datetime.utcnow(),
                is_deleted_remote=False,
            )
            self.db.add(mapping)

        # Update reminders if coming from Google
        if reminder_configs and schedule:
            from app.services.reminder_service import ReminderService
            ReminderService().create_reminders_for_schedule(
                schedule=schedule,
                reminder_configs=reminder_configs,
                db=self.db,
            )

        # Only update fields that weren't set in constructor (for existing mappings)
        if mapping.provider_etag is None:
            mapping.provider_etag = event.get("etag")
        if mapping.provider_updated_at is None:
            mapping.provider_updated_at = provider_updated_at
        mapping.last_sync_source = SyncSource.PROVIDER
        mapping.last_synced_at = datetime.utcnow()
        mapping.is_deleted_remote = False
        self.db.add(mapping)
        self.db.flush()

    def _apply_google_deleted_event(
        self,
        connection: CalendarConnection,
        mapping: ScheduleExternalMap | None,
        event: dict,
        stats: dict[str, int],
    ) -> None:
        schedule = self._resolve_schedule_from_event(connection, event)
        if schedule is None and mapping is not None:
            schedule = self.db.query(Schedule).filter(
                Schedule.id == mapping.schedule_id,
                Schedule.user_id == mapping.user_id,
            ).first()

        mappings_to_delete: list[ScheduleExternalMap] = []
        if mapping is not None:
            mappings_to_delete.append(mapping)
        elif schedule is not None:
            mappings_to_delete = self.db.query(ScheduleExternalMap).filter(
                ScheduleExternalMap.provider == CalendarProvider.GOOGLE,
                ScheduleExternalMap.schedule_id == schedule.id,
            ).all()

        if schedule is None and not mappings_to_delete:
            stats["skipped"] += 1
            return

        # Phase 1: delete external mappings and flush first to satisfy FK constraints.
        for item in mappings_to_delete:
            self.db.delete(item)
        self.db.flush()

        # Phase 2: once mappings are gone, schedule deletion is safe.
        if schedule is not None:
            self.db.delete(schedule)
        self.db.flush()
        stats["deleted"] += 1

    def _resolve_mapping_for_event(
        self,
        connection: CalendarConnection,
        event_id: str,
        event: dict,
    ) -> ScheduleExternalMap | None:
        mapping = self.db.query(ScheduleExternalMap).filter(
            ScheduleExternalMap.provider == CalendarProvider.GOOGLE,
            ScheduleExternalMap.provider_calendar_id == connection.provider_calendar_id,
            ScheduleExternalMap.provider_event_id == event_id,
        ).first()
        if mapping is not None:
            return mapping

        schedule = self._resolve_schedule_from_event(connection, event)
        if schedule is None:
            return None

        return self.db.query(ScheduleExternalMap).filter(
            ScheduleExternalMap.provider == CalendarProvider.GOOGLE,
            ScheduleExternalMap.schedule_id == schedule.id,
        ).first()

    def _resolve_schedule_from_event(self, connection: CalendarConnection, event: dict) -> Schedule | None:
        private = (event.get("extendedProperties") or {}).get("private") or {}
        raw_schedule_id = private.get("cortexScheduleId")
        if not raw_schedule_id:
            return None

        try:
            schedule_id = UUID(str(raw_schedule_id))
        except (ValueError, TypeError):
            return None

        return self.db.query(Schedule).filter(
            Schedule.id == schedule_id,
            Schedule.user_id == connection.user_id,
        ).first()

    def _create_schedule_from_google_event(
        self,
        connection: CalendarConnection,
        event: dict,
        parsed_start: datetime,
        parsed_end: datetime,
        recurrence_rule: dict = None,
    ) -> Schedule:
        schedule = Schedule(
            user_id=connection.user_id,
            title=event.get("summary") or "Untitled",
            type=self._schedule_type_from_google(event),
            start_time=parsed_start,
            end_time=parsed_end,
            location=event.get("location"),
            description=event.get("description"),
            is_completed=False,
            recurrence_rule=recurrence_rule,
        )
        self.db.add(schedule)
        self.db.flush()
        return schedule

    def _update_schedule_from_google_event(
        self,
        schedule: Schedule,
        event: dict,
        parsed_start: datetime,
        parsed_end: datetime,
        recurrence_rule: dict = None,
    ) -> None:
        schedule.title = event.get("summary") or "Untitled"
        schedule.type = self._schedule_type_from_google(event)
        schedule.start_time = parsed_start
        schedule.end_time = parsed_end
        schedule.location = event.get("location")
        schedule.description = event.get("description")
        if recurrence_rule:
            schedule.recurrence_rule = recurrence_rule
        schedule.updated_at = datetime.utcnow()
        self.db.add(schedule)

    def _schedule_type_from_google(self, event: dict) -> ScheduleType:
        private = (event.get("extendedProperties") or {}).get("private") or {}
        raw_type = private.get("cortexType")
        if not raw_type:
            return ScheduleType.PERSONAL
        try:
            return ScheduleType(raw_type)
        except Exception:
            return ScheduleType.PERSONAL

    def _parse_google_event_time(self, payload: dict | None) -> datetime | None:
        if not payload:
            return None

        date_time = payload.get("dateTime")
        if date_time:
            try:
                dt = datetime.fromisoformat(date_time.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    return dt
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
            except ValueError:
                return None

        all_day_date = payload.get("date")
        if all_day_date:
            try:
                dt = datetime.fromisoformat(all_day_date)
                return datetime(dt.year, dt.month, dt.day)
            except ValueError:
                return None

        return None

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
        payload = {
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
                    "cortexVersion": str(schedule.version),
                }
            },
        }

        # Recurrence
        if schedule.recurrence_rule:
            rrule_str = RecurrenceService().build_rrule_string(schedule.recurrence_rule)
            if rrule_str:
                payload["recurrence"] = [rrule_str]

        # Reminders
        if hasattr(schedule, 'reminders') and schedule.reminders:
            overrides = [
                {
                    "method": "popup" if r.method.value == "push" else "email",
                    "minutes": r.minutes_before,
                }
                for r in schedule.reminders
                if r.status not in (ReminderStatus.CANCELLED, ReminderStatus.SENT)
            ]
            if overrides:
                payload["reminders"] = {
                    "useDefault": False,
                    "overrides": overrides,
                }
            else:
                payload["reminders"] = {"useDefault": True}
        else:
            payload["reminders"] = {"useDefault": True}

        # If exception (single instance edited), add originalStartTime
        if schedule.is_exception and schedule.original_start_time:
            payload["originalStartTime"] = {
                "dateTime": self._to_rfc3339_utc(schedule.original_start_time),
                "timeZone": "UTC",
            }

        return payload

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
