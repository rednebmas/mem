"""Apple Reminders collector — one-time (non-recurring) reminders."""

import os
import sqlite3
from datetime import datetime, timedelta

from .shared import format_time_range
from .base import Collector

REMINDERS_STORE_DIR = os.path.expanduser(
    "~/Library/Group Containers/group.com.apple.reminders/Container_v1/Stores"
)

MACOS_EPOCH = datetime(2001, 1, 1)


def _find_active_db():
    """Find the Reminders SQLite DB that has actual data."""
    if not os.path.isdir(REMINDERS_STORE_DIR):
        return None
    for fname in os.listdir(REMINDERS_STORE_DIR):
        if not fname.endswith(".sqlite"):
            continue
        path = os.path.join(REMINDERS_STORE_DIR, fname)
        try:
            conn = sqlite3.connect(path)
            count = conn.execute(
                "SELECT COUNT(*) FROM ZREMCDREMINDER WHERE ZMARKEDFORDELETION = 0"
            ).fetchone()[0]
            conn.close()
            if count > 0:
                return path
        except Exception:
            continue
    return None


class RemindersCollector(Collector):
    name = "reminders"
    description = "Apple Reminders (one-time, non-recurring)"
    platform_required = "Darwin"

    def collect(self, since_dt, until_dt=None):
        db_path = _find_active_db()
        if not db_path:
            return None

        conn = sqlite3.connect(db_path)

        since_offset = (since_dt - MACOS_EPOCH).total_seconds()
        query = """
            SELECT r.ZTITLE, r.ZFLAGGED, r.ZCREATIONDATE, r.ZDUEDATE
            FROM ZREMCDREMINDER r
            LEFT JOIN ZREMCDOBJECT o ON o.ZREMINDER4 = r.Z_PK AND o.ZFREQUENCY IS NOT NULL
            WHERE r.ZMARKEDFORDELETION = 0
                AND r.ZCOMPLETED = 0
                AND o.Z_PK IS NULL
                AND r.ZCREATIONDATE >= ?
        """
        params = [since_offset]

        if until_dt:
            until_offset = (until_dt - MACOS_EPOCH).total_seconds()
            query += " AND r.ZCREATIONDATE < ?"
            params.append(until_offset)

        query += " ORDER BY r.ZCREATIONDATE DESC"
        rows = conn.execute(query, params).fetchall()
        conn.close()

        if not rows:
            return None

        total = len(rows)
        lines = [f"# Reminders ({format_time_range(since_dt)}, {total} new)"]

        for title, flagged, creation_ts, due_ts in rows:
            due_str = ""
            if due_ts:
                due_dt = MACOS_EPOCH + timedelta(seconds=due_ts)
                due_str = f", due {due_dt.strftime('%m/%d %H:%M')}"
            flag_str = " [flagged]" if flagged else ""
            created_dt = MACOS_EPOCH + timedelta(seconds=creation_ts)
            lines.append(f"  [{created_dt.strftime('%m/%d %H:%M')}] {title}{due_str}{flag_str}")

        return "\n".join(lines)
