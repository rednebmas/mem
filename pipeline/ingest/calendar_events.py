"""Google Calendar source - noise-filtered item lists."""

import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'lib'))

from google_auth import get_calendar_service
from .shared import format_time_range
from .base import Source

GCAL_BOILERPLATE = "To see detailed information for automatically created events"


def _format_event_time(event):
    start = event["start"].get("dateTime", event["start"].get("date"))
    if "T" in start:
        dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        return dt.strftime("%a %m/%d %I:%M%p").lower()
    dt = datetime.strptime(start, "%Y-%m-%d")
    return dt.strftime("%a %m/%d") + " all-day"


def _fetch_events(since_dt, until_dt=None):
    service = get_calendar_service()
    now = datetime.now(timezone.utc)
    time_min = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if since_dt else (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    time_max = until_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if until_dt else (now + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        maxResults=50,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return result.get("items", [])


class CalendarSource(Source):
    name = "calendar"
    description = "Google Calendar events"

    def collect(self, since_dt, until_dt=None):
        events = _fetch_events(since_dt, until_dt)
        if not events:
            return None

        lines = [f"# Calendar ({format_time_range(since_dt)})"]
        for event in events:
            summary = event.get("summary", "(No title)")
            time_str = _format_event_time(event)
            line = f'- "{summary}" ({time_str})'
            loc = event.get("location", "")
            if loc:
                line += f" @ {loc}"
            desc = event.get("description", "")
            if desc and not desc.startswith(GCAL_BOILERPLATE):
                line += f"\n  {desc}"
            lines.append(line)

        return "\n".join(lines)
