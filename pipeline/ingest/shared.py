"""Shared constants and helpers for ingestion sources."""

import re
from datetime import datetime

IMESSAGE_REACTION_RE = re.compile(
    r'^(Loved|Liked|Disliked|Laughed at|Emphasized|Questioned|Reacted \S+ to) ["\u201c](.*)["\u201d]$',
    re.DOTALL,
)

# Page titles that are generic noise (login, auth, empty pages)
NOISE_TITLE_PATTERNS = re.compile(
    r"^(sign in|log ?in|log ?out|google accounts?|new tab|untitled|about:blank|inbox \(\d+\) -.*|google drive|my drive - google drive|home - google drive)$",
    re.IGNORECASE,
)

# URL path patterns that indicate noise (login/auth/callback pages)
NOISE_PATH_PATTERNS = re.compile(
    r"/(oauth|callback|verify)/",
    re.IGNORECASE,
)


def is_noise_entry(url, title):
    if NOISE_TITLE_PATTERNS.match(title.strip()):
        return True
    if NOISE_PATH_PATTERNS.search(url):
        return True
    return False


def format_time_range(since_dt):
    if not since_dt:
        return "all time"
    days = (datetime.now() - since_dt).days
    if days <= 1:
        return "last 24 hours"
    if days <= 7:
        return f"last {days} days"
    if days <= 30:
        weeks = max(1, days // 7)
        return f"last {weeks} week{'s' if weeks > 1 else ''}"
    return f"last {days} days"


def extract_email_name(header_value):
    """Extract human-readable name from 'Name <email>' or bare email."""
    if not header_value:
        return None
    match = re.match(r'"?([^"<]+?)"?\s*<', header_value)
    if match and match.group(1).strip():
        return match.group(1).strip()
    email_match = re.match(r'([^@]+)@', header_value.strip())
    if email_match:
        local = email_match.group(1)
        parts = re.split(r'[._\-+]', local)
        if parts and not all(p.isdigit() for p in parts):
            return " ".join(p.capitalize() for p in parts if p)
    return header_value.strip() or None
