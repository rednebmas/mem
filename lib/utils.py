"""Shared utilities for mem CLI tools."""

import re
import sys
from datetime import datetime, timedelta


def parse_since(since_str):
    """
    Parse relative time string like '3d', '1w', '2h' into datetime.

    Supported units:
        h - hours
        d - days
        w - weeks
        m - months (30 days)

    Returns None if since_str is None.
    Exits with error if format is invalid.
    """
    if not since_str:
        return None

    match = re.match(r'^(\d+)([dhwm])$', since_str.lower())
    if not match:
        print(f"Error: Invalid --since format '{since_str}'. Use format like '3d', '1w', '2h', '1m'", file=sys.stderr)
        sys.exit(1)

    amount = int(match.group(1))
    unit = match.group(2)

    now = datetime.now()
    if unit == 'h':
        return now - timedelta(hours=amount)
    elif unit == 'd':
        return now - timedelta(days=amount)
    elif unit == 'w':
        return now - timedelta(weeks=amount)
    elif unit == 'm':
        return now - timedelta(days=amount * 30)

    return None


def macos_to_datetime(macos_timestamp):
    """Convert macOS epoch timestamp (nanoseconds since 2001-01-01) to datetime."""
    return datetime.fromtimestamp((macos_timestamp / 1e9) + 978307200)


def datetime_to_macos(dt):
    """Convert datetime to macOS epoch timestamp."""
    return int((dt.timestamp() - 978307200) * 1e9)
