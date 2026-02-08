"""Phone call history source — answered calls from macOS CallHistory DB."""

import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'lib'))

from contacts import ContactResolver
from .shared import format_time_range
from .base import Source

CALL_HISTORY_DB = os.path.expanduser(
    "~/Library/Application Support/CallHistoryDB/CallHistory.storedata"
)

MACOS_EPOCH = datetime(2001, 1, 1)


def _format_duration(seconds):
    """Convert seconds to human-readable duration."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} sec"
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours > 0:
        if minutes > 0:
            return f"{hours} hr {minutes} min"
        return f"{hours} hr"
    return f"{minutes} min"


class CallsSource(Source):
    name = "calls"
    description = "Phone call history"
    platform_required = "Darwin"

    def collect(self, since_dt, until_dt=None):
        if not os.path.exists(CALL_HISTORY_DB):
            return None

        conn = sqlite3.connect(CALL_HISTORY_DB)
        cursor = conn.cursor()

        since_offset = (since_dt - MACOS_EPOCH).total_seconds()
        query = """
            SELECT ZDATE, ZDURATION, ZADDRESS, ZORIGINATED
            FROM ZCALLRECORD
            WHERE ZANSWERED = 1 AND ZDURATION > 0 AND ZDATE >= ?
        """
        params = [since_offset]

        if until_dt:
            until_offset = (until_dt - MACOS_EPOCH).total_seconds()
            query += " AND ZDATE < ?"
            params.append(until_offset)

        query += " ORDER BY ZDATE DESC"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return None

        resolver = ContactResolver()
        by_contact = defaultdict(list)

        for zdate, duration, address, originated in rows:
            ts = MACOS_EPOCH + timedelta(seconds=zdate)
            name = resolver.resolve(address) if address else address or "Unknown"
            direction = "Outgoing" if originated else "Incoming"
            by_contact[name].append({
                "timestamp": ts,
                "direction": direction,
                "duration": _format_duration(duration),
            })

        sorted_contacts = sorted(by_contact.items(), key=lambda x: -len(x[1]))
        total_calls = sum(len(calls) for calls in by_contact.values())

        lines = [f"# Calls ({format_time_range(since_dt)}, {total_calls} call{'s' if total_calls != 1 else ''})"]

        for name, calls in sorted_contacts:
            count_label = f"{len(calls)} call{'s' if len(calls) != 1 else ''}"
            lines.append(f"\n{name} ({count_label}):")
            for c in sorted(calls, key=lambda c: c["timestamp"]):
                lines.append(f"  [{c['timestamp'].strftime('%m/%d %H:%M')}] {c['direction']}, {c['duration']}")

        return "\n".join(lines)
