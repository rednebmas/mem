"""Browser history database readers for Chrome and Safari."""

import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs

CHROME_DIR = Path.home() / "Library/Application Support/Google/Chrome"
SAFARI_HISTORY = Path.home() / "Library/Safari/History.db"

CHROME_EPOCH_OFFSET = 11644473600000000  # microseconds since 1601-01-01
SAFARI_EPOCH_OFFSET = 978307200  # seconds since 2001-01-01


def copy_db(src):
    if not src.exists():
        return None
    tmp = Path(tempfile.mkdtemp()) / src.name
    shutil.copy2(src, tmp)
    for ext in ["-wal", "-shm"]:
        wal = Path(str(src) + ext)
        if wal.exists():
            shutil.copy2(wal, Path(str(tmp) + ext))
    return tmp


def _query_db(db_path, sql, params, ts_fn, browser, label=None):
    try:
        tmp = copy_db(db_path)
        if not tmp:
            return []
        conn = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [
            {"url": url, "title": title or "", "browser": browser,
             "timestamp": datetime.fromtimestamp(ts_fn(vt))}
            for url, title, vt in rows
        ]
    except Exception as e:
        name = label or browser
        print(f"Warning: Could not read {name} history: {e}", file=sys.stderr)
        return []
    finally:
        if 'tmp' in locals() and tmp:
            tmp.unlink(missing_ok=True)


def find_chrome_profiles():
    if not CHROME_DIR.exists():
        return []
    profiles = []
    for candidate in ["Default"] + [f"Profile {i}" for i in range(1, 20)]:
        history = CHROME_DIR / candidate / "History"
        if history.exists():
            profiles.append(history)
    return profiles


def read_chrome(since_dt=None, until_dt=None):
    entries = []
    for profile in find_chrome_profiles():
        sql = "SELECT u.url, u.title, v.visit_time FROM visits v JOIN urls u ON v.url = u.id"
        params = []
        clauses = []
        if since_dt:
            chrome_time = int(since_dt.timestamp() * 1_000_000) + CHROME_EPOCH_OFFSET
            clauses.append("v.visit_time >= ?")
            params.append(chrome_time)
        if until_dt:
            chrome_time = int(until_dt.timestamp() * 1_000_000) + CHROME_EPOCH_OFFSET
            clauses.append("v.visit_time < ?")
            params.append(chrome_time)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY v.visit_time DESC"
        ts_fn = lambda t: (t - CHROME_EPOCH_OFFSET) / 1_000_000
        entries.extend(_query_db(profile, sql, params, ts_fn, "chrome", profile.parent.name))
    return entries


def read_safari(since_dt=None, until_dt=None):
    sql = "SELECT hi.url, hv.title, hv.visit_time FROM history_visits hv JOIN history_items hi ON hv.history_item = hi.id"
    params = []
    clauses = []
    if since_dt:
        clauses.append("hv.visit_time >= ?")
        params.append(since_dt.timestamp() - SAFARI_EPOCH_OFFSET)
    if until_dt:
        clauses.append("hv.visit_time < ?")
        params.append(until_dt.timestamp() - SAFARI_EPOCH_OFFSET)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY hv.visit_time DESC"
    ts_fn = lambda t: t + SAFARI_EPOCH_OFFSET
    return _query_db(SAFARI_HISTORY, sql, params, ts_fn, "safari")


def merge_and_dedupe(entries):
    seen = set()
    deduped = []
    for entry in sorted(entries, key=lambda e: e["timestamp"], reverse=True):
        key = (entry["url"], entry["timestamp"].strftime("%Y-%m-%d %H:%M"))
        if key not in seen:
            seen.add(key)
            deduped.append(entry)
    return deduped


def read_all(since_dt=None, until_dt=None, browser=None):
    entries = []
    if browser is None or browser == "chrome":
        entries.extend(read_chrome(since_dt, until_dt))
    if browser is None or browser == "safari":
        entries.extend(read_safari(since_dt, until_dt))
    return merge_and_dedupe(entries)


def extract_search_query(url):
    parsed = urlparse(url)
    if parsed.hostname and "google.com" in parsed.hostname and parsed.path == "/search":
        return parse_qs(parsed.query).get("q", [None])[0]
    return None


def get_domain(url):
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""
