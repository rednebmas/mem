"""CLI entry point for the topics pipeline: ingest → route + contextualize.

Processes data since the last successful run (watermark-based).
Falls back to last 24h if no watermark exists.
"""

import io
import sys
import time
from datetime import datetime, timedelta, timezone

from . import config
from .ingest import collect_all, format_output, SOURCE_NAMES
from .topic_db import format_topic_tree, get_topic_tree, generate_topics_file
from .topics_route import route_all
from .actions import load_actions, dispatch


class TeeWriter:
    """Write to both a stream and a buffer."""
    def __init__(self, stream):
        self.stream = stream
        self.buffer = io.StringIO()

    def write(self, text):
        self.stream.write(text)
        self.buffer.write(text)

    def flush(self):
        self.stream.flush()

    def getvalue(self):
        return self.buffer.getvalue()


def load_watermark():
    """Load last run timestamp. Returns naive local datetime, or None."""
    wm = config.get_watermark_path()
    if not wm.exists():
        return None
    try:
        text = wm.read_text().strip()
        utc_dt = datetime.fromisoformat(text)
        return utc_dt.astimezone().replace(tzinfo=None)
    except (ValueError, OSError):
        return None


def save_watermark():
    """Save current UTC time as the watermark."""
    wm = config.get_watermark_path()
    wm.write_text(datetime.now(timezone.utc).isoformat() + "\n")


def run_pipeline(since_dt, until_dt, sources=None, dry_run=False):
    """Run one pipeline pass for the given time window."""
    results = collect_all(since_dt, sources, until_dt=until_dt)
    if not results:
        print("  No data collected.")
        return 0
    for name, items in results.items():
        lines = items.count("\n") + 1
        print(f"  {name}: {lines} lines")

    if dry_run:
        print("\n" + format_output(results))
        return 0

    actions = load_actions()
    total_updates, result = route_all(results, activity_date=since_dt, actions=actions)
    print(f"  {total_updates} topic updates")

    if actions and result:
        dispatch(actions, result)

    return total_updates


def main(args=None):
    """Run the pipeline. Can be called with pre-parsed args or uses sys.argv."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Run the topics pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  mem run <dir>                        # Since last run (or last 24h)
  mem run <dir> --date 2026-02-01      # Specific date (bypasses watermark)
  mem run <dir> --dry-run              # Show ingestion output without LLM
  mem run <dir> --source browser       # Single source only
        """,
    )
    parser.add_argument("--date", "-d", help="Date to process (YYYY-MM-DD, bypasses watermark)")
    parser.add_argument("--source", nargs="+", choices=SOURCE_NAMES)
    parser.add_argument("--dry-run", action="store_true", help="Only run ingestion, skip LLM")

    parsed = parser.parse_args(args)

    if parsed.date:
        since_dt = datetime.strptime(parsed.date, "%Y-%m-%d")
        until_dt = since_dt + timedelta(days=1)
        label = since_dt.strftime("%b %d")
    else:
        watermark = load_watermark()
        if watermark:
            since_dt = watermark
            label = f"since {since_dt.strftime('%b %d %H:%M')}"
        else:
            since_dt = datetime.now() - timedelta(days=1)
            label = "last 24h (no watermark)"
        until_dt = datetime.now()

    tee_out = TeeWriter(sys.stdout)
    tee_err = TeeWriter(sys.stderr)
    sys.stdout = tee_out
    sys.stderr = tee_err

    pipeline_start = time.time()
    print(f"=== {label} ===")
    run_pipeline(since_dt, until_dt, parsed.source, parsed.dry_run)

    if not parsed.dry_run:
        print(f"\n=== Generating MEMORY.md ===")
        generate_topics_file()

    elapsed = time.time() - pipeline_start
    print(f"\n=== Done in {elapsed:.0f}s ===")

    if not parsed.dry_run and not parsed.date:
        save_watermark()

    topics = get_topic_tree()
    print(format_topic_tree(topics))

    # Restore streams and write pipeline log
    sys.stdout = tee_out.stream
    sys.stderr = tee_err.stream
    debug_dir = config.get_debug_dir()
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_path = debug_dir / f"{ts}_pipeline_run.md"
    log_path.write_text(
        f"# Pipeline Run: {label}\n\n```\n{tee_out.getvalue()}{tee_err.getvalue()}```\n"
    )
    print(f"  Pipeline log: {log_path}")
