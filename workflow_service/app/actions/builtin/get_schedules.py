from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from app.actions.base import BaseAction, ActionContext, ActionResult
from app.config import settings


class GetSchedulesAction(BaseAction):

    @property
    def action_type(self) -> str:
        return "action.get_schedules"

    @property
    def display_name(self) -> str:
        return "Lấy Lịch Trình"

    @property
    def description(self) -> str:
        return "Lấy lịch trình hôm nay của người dùng"

    @property
    def config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "title": "Múi giờ",
                    "description": "IANA timezone, ví dụ Asia/Ho_Chi_Minh. Mặc định UTC.",
                }
            },
        }

    async def execute(self, config: dict, context: ActionContext) -> ActionResult:
        try:
            tz = ZoneInfo(config.get("timezone") or "UTC")
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("UTC")

        today_local = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        start_date = today_local
        end_date = today_local + timedelta(days=1)

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{settings.cortex_backend_url}/api/schedules",
                    params={
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                    },
                    headers={
                        "X-Internal-API-Key": settings.cortex_internal_api_key,
                        "X-User-ID": context.user_id,
                    },
                    timeout=10.0,
                )
                response.raise_for_status()
                data = response.json()

                schedules = [
                    {
                        "title": item.get("title"),
                        "start_time": item.get("start_time"),
                        "end_time": item.get("end_time"),
                        "location": item.get("location"),
                        "description": item.get("description"),
                    }
                    for item in data.get("items", [])
                ]
                schedules.sort(key=lambda s: s["start_time"] or "")

                return ActionResult(
                    success=True,
                    output={
                        "schedules": schedules,
                        "count": len(schedules),
                        "date": today_local.date().isoformat(),
                        "summary_text": self._format_summary(schedules),
                    },
                )

            except httpx.HTTPError as e:
                return ActionResult(
                    success=False,
                    output={},
                    error=f"Failed to fetch schedules: {str(e)}",
                )

    @staticmethod
    def _format_summary(schedules: list[dict]) -> str:
        if not schedules:
            return "Hôm nay bạn không có lịch trình nào."

        def hhmm(iso_str: str | None) -> str:
            if not iso_str:
                return "?"
            try:
                return datetime.fromisoformat(iso_str).strftime("%H:%M")
            except ValueError:
                return "?"

        lines = [f"Lịch trình hôm nay ({len(schedules)} việc):"]
        for s in schedules:
            lines.append(f"- {hhmm(s['start_time'])}–{hhmm(s['end_time'])}: {s['title']}")
        return "\n".join(lines)
