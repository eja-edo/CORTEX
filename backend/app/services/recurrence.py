"""Recurrence service for generating and managing recurring schedule instances."""

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict
from uuid import UUID
from zoneinfo import ZoneInfo

from dateutil.rrule import rrule, WEEKLY, DAILY, MONTHLY, MO, TU, WE, TH, FR, SA, SU
from dateutil.parser import parse as parse_dt
from sqlalchemy.orm import Session

from app.models import Schedule
from app.utils.logger import get_logger

logger = get_logger(__name__)

BYDAY_MAP = {
    "MO": MO, "TU": TU, "WE": WE, "TH": TH,
    "FR": FR, "SA": SA, "SU": SU
}
FREQ_MAP = {
    "DAILY": DAILY, "WEEKLY": WEEKLY, "MONTHLY": MONTHLY
}


def _to_naive_utc(dt: datetime) -> datetime:
    """Convert datetime to naive UTC. If already naive, return as-is."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


class RecurrenceService:
    """Service for handling recurring event logic."""

    def generate_instances(
        self,
        root: Schedule,
        range_start: datetime,
        range_end: datetime,
        db: Session,
    ) -> List[dict]:
        """
        Generate virtual instances for a recurring event within a time range.
        Returns list of dict (not DB objects).
        Instances already in DB (is_exception=True or is_cancelled=True) will be merged.
        
        For WEEKLY: Uses the weekday from root.start_time (no byday needed)
        For MONTHLY: Uses the day-of-month from root.start_time
        """
        # Normalize range boundaries to naive UTC to avoid comparison errors
        range_start = _to_naive_utc(range_start)
        range_end = _to_naive_utc(range_end)

        rule = root.recurrence_rule
        if not rule or rule.get("freq") == "NONE":
            # Non-recurring: return root if in range
            root_start = _to_naive_utc(root.start_time)
            if range_start <= root_start <= range_end:
                return [self._schedule_to_dict(root)]
            return []

        freq = FREQ_MAP.get(rule["freq"])
        if freq is None:
            logger.warning("Unknown recurrence frequency: %s", rule.get("freq"))
            return []

        interval = rule.get("interval", 1)
        tzid = rule.get("tzid", "UTC")
        tz = ZoneInfo(tzid)
        duration = root.end_time - root.start_time

        # Build rrule kwargs
        dtstart = root.start_time
        if dtstart.tzinfo is None:
            dtstart = dtstart.replace(tzinfo=tz)

        kwargs = {
            "freq": freq,
            "interval": interval,
            "dtstart": dtstart,
        }

        if rule.get("until"):
            try:
                kwargs["until"] = parse_dt(rule["until"])
            except Exception as e:
                logger.warning("Failed to parse until date: %s", e)

        if rule.get("count"):
            kwargs["count"] = rule["count"]

        try:
            # rrule.between requires both boundaries to share timezone awareness with dtstart.
            # dtstart is aware (tz-attached), so pass aware boundaries.
            aware_range_start = range_start.replace(tzinfo=timezone.utc)
            aware_range_end = range_end.replace(tzinfo=timezone.utc)
            occurrences_raw = list(rrule(**kwargs).between(aware_range_start, aware_range_end, inc=True))
            # Normalize back to naive UTC for consistent downstream usage
            occurrences = [_to_naive_utc(occ) for occ in occurrences_raw]
        except Exception as e:
            logger.exception("Failed to generate recurrence occurrences: %s", e)
            return []

        # Load exceptions already in DB
        exceptions_by_original = self._load_exceptions(root.id, db)

        results = []
        for occ_start in occurrences:
            occ_key = occ_start.isoformat()

            # Also check aware version of the key in case exceptions were stored with tz
            occ_key_aware = occ_start.replace(tzinfo=timezone.utc).isoformat()

            matched_exc = exceptions_by_original.get(occ_key) or exceptions_by_original.get(occ_key_aware)

            if matched_exc:
                if not matched_exc.is_cancelled:
                    results.append(self._schedule_to_dict(matched_exc, is_instance=True))
                # is_cancelled => skip (don't append)
            else:
                # Virtual instance
                results.append({
                    "id": str(root.id),
                    "user_id": str(root.user_id),
                    "title": root.title,
                    "type": root.type.value if hasattr(root.type, 'value') else root.type,
                    "start_time": occ_start.isoformat(),
                    "end_time": (occ_start + duration).isoformat(),
                    "location": root.location,
                    "description": root.description,
                    "is_completed": root.is_completed,
                    "recurrence": root.recurrence_rule,
                    "is_recurring": True,
                    "is_exception": False,
                    "is_cancelled": False,
                    "recurrence_id": str(root.id),
                    "original_start_time": occ_start.isoformat(),
                    "is_virtual": True,
                    "version": root.version,
                    "created_at": root.created_at.isoformat() if root.created_at else None,
                    "updated_at": root.updated_at.isoformat() if root.updated_at else None,
                })

        return results

    def _load_exceptions(self, root_id: UUID, db: Session) -> dict:
        """Load all modified/cancelled instances for a series."""
        exceptions = db.query(Schedule).filter(
            Schedule.recurrence_id == root_id,
        ).all()

        result = {}
        for exc in exceptions:
            if exc.original_start_time is not None:
                # Store both naive and aware keys for flexible lookup
                naive_dt = _to_naive_utc(exc.original_start_time)
                result[naive_dt.isoformat()] = exc
                # Also store the original isoformat as fallback
                result[exc.original_start_time.isoformat()] = exc
        return result

    def _schedule_to_dict(self, schedule: Schedule, is_instance: bool = False) -> dict:
        """Convert Schedule object to dict for API response."""
        return {
            "id": str(schedule.id),
            "user_id": str(schedule.user_id),
            "title": schedule.title,
            "type": schedule.type.value if hasattr(schedule.type, 'value') else schedule.type,
            "start_time": schedule.start_time.isoformat() if schedule.start_time else None,
            "end_time": schedule.end_time.isoformat() if schedule.end_time else None,
            "location": schedule.location,
            "description": schedule.description,
            "is_completed": schedule.is_completed,
            "recurrence": schedule.recurrence_rule,
            "is_recurring": self.is_recurring(schedule.recurrence_rule),
            "is_exception": schedule.is_exception,
            "is_cancelled": schedule.is_cancelled,
            "recurrence_id": str(schedule.recurrence_id) if schedule.recurrence_id else None,
            "original_start_time": schedule.original_start_time.isoformat() if schedule.original_start_time else None,
            "is_virtual": False,
            "version": schedule.version,
            "created_at": schedule.created_at.isoformat() if schedule.created_at else None,
            "updated_at": schedule.updated_at.isoformat() if schedule.updated_at else None,
        }

    def build_rrule_string(self, rule: dict) -> Optional[str]:
        """Convert internal rule to RRULE string for Google Calendar."""
        if not rule or rule.get("freq") == "NONE":
            return None

        parts = [f"FREQ={rule['freq']}", f"INTERVAL={rule.get('interval', 1)}"]

        if rule.get("until"):
            try:
                until_dt = parse_dt(rule["until"]).astimezone(ZoneInfo("UTC"))
                parts.append(f"UNTIL={until_dt.strftime('%Y%m%dT%H%M%SZ')}")
            except Exception as e:
                logger.warning("Failed to parse until date for RRULE: %s", e)

        if rule.get("count"):
            parts.append(f"COUNT={rule['count']}")

        return "RRULE:" + ";".join(parts)

    def parse_google_rrule(self, rrule_str: str) -> dict | None:
        """Parse RRULE string from Google to internal format. Returns None if no recurrence."""
        if not rrule_str or not rrule_str.startswith("RRULE:"):
            return None

        rule = {}
        for part in rrule_str[6:].split(";"):
            key, _, val = part.partition("=")
            rule[key] = val

        result = {
            "freq": rule.get("FREQ", "NONE"),
            "interval": int(rule.get("INTERVAL", 1)),
        }

        if "UNTIL" in rule:
            result["until"] = rule["UNTIL"]

        if "COUNT" in rule:
            result["count"] = int(rule["COUNT"])

        if "TZID" in rule:
            result["tzid"] = rule["TZID"]

        return result

    def is_recurring(self, rule: dict | None) -> bool:
        """Check if a recurrence rule represents a recurring event."""
        return rule is not None and rule.get("freq") != "NONE"