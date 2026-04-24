"""Recurrence service for generating and managing recurring schedule instances."""

from datetime import datetime, timedelta
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
        rule = root.recurrence_rule
        if not rule or rule.get("freq") == "NONE":
            # Non-recurring: return root if in range
            if range_start <= root.start_time <= range_end:
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

        # For WEEKLY: automatically use the weekday from start_time
        # No need for byday - rrule uses dtstart's weekday by default
        # For MONTHLY: automatically uses the day-of-month from start_time
        # No extra config needed - rrule uses dtstart's day by default

        if rule.get("until"):
            try:
                kwargs["until"] = parse_dt(rule["until"])
            except Exception as e:
                logger.warning("Failed to parse until date: %s", e)

        if rule.get("count"):
            kwargs["count"] = rule["count"]

        try:
            occurrences = list(rrule(**kwargs).between(range_start, range_end, inc=True))
        except Exception as e:
            logger.exception("Failed to generate recurrence occurrences: %s", e)
            return []

        # Load exceptions already in DB
        exceptions_by_original = self._load_exceptions(root.id, db)

        results = []
        for occ_start in occurrences:
            occ_key = occ_start.isoformat()

            if occ_key in exceptions_by_original:
                exc = exceptions_by_original[occ_key]
                if not exc.is_cancelled:
                    results.append(self._schedule_to_dict(exc, is_instance=True))
                # is_cancelled => skip (don't append)
            else:
                # Virtual instance - include ALL required fields for ScheduleResponse
                results.append({
                    "id": None,  # Not in DB yet - will cause validation error, need to make optional
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
                    "is_virtual": True,  # client flag
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
                key = exc.original_start_time.isoformat()
                result[key] = exc
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
            "is_recurring": schedule.recurrence_rule is not None and schedule.recurrence_rule.get("freq") != "NONE",
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

        # No byday needed - Google will use DTSTART's weekday automatically

        if rule.get("until"):
            # Google needs format YYYYMMDDTHHMMSSZ
            try:
                until_dt = parse_dt(rule["until"]).astimezone(ZoneInfo("UTC"))
                parts.append(f"UNTIL={until_dt.strftime('%Y%m%dT%H%M%SZ')}")
            except Exception as e:
                logger.warning("Failed to parse until date for RRULE: %s", e)

        if rule.get("count"):
            parts.append(f"COUNT={rule['count']}")

        return "RRULE:" + ";".join(parts)

    def parse_google_rrule(self, rrule_str: str) -> dict:
        """Parse RRULE string from Google to internal format."""
        if not rrule_str or not rrule_str.startswith("RRULE:"):
            return {"freq": "NONE"}

        rule = {}
        for part in rrule_str[6:].split(";"):
            key, _, val = part.partition("=")
            rule[key] = val

        result = {
            "freq": rule.get("FREQ", "NONE"),
            "interval": int(rule.get("INTERVAL", 1)),
        }

        # Ignore BYDAY - we use DTSTART's weekday automatically
        # if "BYDAY" in rule:
        #     result["byday"] = rule["BYDAY"].split(",")

        if "UNTIL" in rule:
            result["until"] = rule["UNTIL"]

        if "COUNT" in rule:
            result["count"] = int(rule["COUNT"])

        if "TZID" in rule:
            result["tzid"] = rule["TZID"]

        return result
