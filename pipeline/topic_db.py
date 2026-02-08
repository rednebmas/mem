"""SQLite helpers for the topic tree and activity log."""

import sqlite3
from collections import defaultdict
from datetime import datetime

from . import config


def _conn():
    return sqlite3.connect(config.get_db_path())


def get_topic_tree():
    """Load all topics as a flat list with parent info.

    Returns list of dicts: [{id, name, parent_id, parent_name, summary}]
    """
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.id, t.name, t.parent_id, p.name as parent_name, t.summary
        FROM topics t
        LEFT JOIN topics p ON t.parent_id = p.id
        ORDER BY t.parent_id NULLS FIRST, t.name
    """)
    topics = []
    for row in cursor.fetchall():
        topics.append({
            "id": row[0], "name": row[1], "parent_id": row[2],
            "parent_name": row[3], "summary": row[4],
        })
    conn.close()
    return topics


def format_topic_tree(topics):
    """Format topic list as indented text for LLM prompts."""
    if not topics:
        return "(no topics yet)"
    by_parent = {}
    for t in topics:
        by_parent.setdefault(t["parent_id"], []).append(t)

    lines = []
    def _render(parent_id, indent=0):
        for t in by_parent.get(parent_id, []):
            prefix = "\t" * indent + "- "
            summary = f": {t['summary']}" if t["summary"] else ""
            lines.append(f"{prefix}{t['name']}{summary}")
            _render(t["id"], indent + 1)

    _render(None)
    return "\n".join(lines)


DECAY_THRESHOLD = 0.1


def compute_decay_scores():
    """Calculate per-topic decay scores from activity timestamps.

    Algorithm: own_score = sum(0.5 ^ (days_since / 14.0)) across all activity.
    Rollup: post-order traversal — each parent accumulates children's total_score.
    Returns: {topic_id: total_score} dict.
    """
    conn = _conn()
    cursor = conn.cursor()
    now = datetime.now()

    cursor.execute("SELECT topic_id, timestamp FROM activity")
    own_scores = defaultdict(float)
    for topic_id, ts_str in cursor.fetchall():
        ts = datetime.fromisoformat(ts_str) if isinstance(ts_str, str) else ts_str
        days = (now - ts).total_seconds() / 86400.0
        own_scores[topic_id] += 0.5 ** (days / 14.0)

    cursor.execute("SELECT id, parent_id FROM topics")
    children_of = defaultdict(list)
    all_ids = []
    parent_of = {}
    for tid, pid in cursor.fetchall():
        all_ids.append(tid)
        parent_of[tid] = pid
        if pid is not None:
            children_of[pid].append(tid)

    conn.close()

    total_scores = {}

    def _accumulate(tid):
        child_sum = 0.0
        for cid in children_of.get(tid, []):
            _accumulate(cid)
            child_sum += total_scores[cid]
        total_scores[tid] = own_scores.get(tid, 0.0) + child_sum

    for tid in all_ids:
        if parent_of[tid] is None and tid not in total_scores:
            _accumulate(tid)
    for tid in all_ids:
        if tid not in total_scores:
            _accumulate(tid)

    return total_scores


def get_latest_activity_dates():
    """Get the most recent activity timestamp per topic. Returns {topic_id: date_string}."""
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute("SELECT topic_id, MAX(timestamp) FROM activity GROUP BY topic_id")
    result = {row[0]: row[1][:10] for row in cursor.fetchall()}
    conn.close()
    return result


def format_topic_tree_for_routing(topics, scores, threshold=DECAY_THRESHOLD):
    """Format topic tree for routing prompt — shows ALL topics.

    Active topics (score >= threshold) show name: summary.
    Inactive topics (score < threshold) show bare name only.
    """
    if not topics:
        return "(no topics yet)"

    id_to_score = scores
    by_parent = {}
    for t in topics:
        by_parent.setdefault(t["parent_id"], []).append(t)

    lines = []

    def _render(parent_id, indent=0):
        for t in by_parent.get(parent_id, []):
            prefix = "\t" * indent + "- "
            score = id_to_score.get(t["id"], 0.0)
            if score >= threshold and t["summary"]:
                lines.append(f"{prefix}{t['name']}: {t['summary']}")
            else:
                lines.append(f"{prefix}{t['name']}")
            _render(t["id"], indent + 1)

    _render(None)
    return "\n".join(lines)


def format_topic_tree_for_output(topics, scores, threshold=DECAY_THRESHOLD):
    """Format topic tree for TOPICS.md — only active topics appear.

    Include a topic if score >= threshold OR it has any descendant above threshold.
    Completely omit topics below threshold with no active descendants.
    """
    if not topics:
        return "(no topics yet)"

    id_to_score = scores
    by_parent = {}
    topic_by_id = {}
    for t in topics:
        by_parent.setdefault(t["parent_id"], []).append(t)
        topic_by_id[t["id"]] = t

    include = set()
    for t in by_parent.get(None, []):
        include.add(t["id"])

    def _mark_active(parent_id):
        for t in by_parent.get(parent_id, []):
            child_active = _mark_active(t["id"])
            if id_to_score.get(t["id"], 0.0) >= threshold or child_active:
                include.add(t["id"])
                return True
        return False

    _mark_active(None)

    lines = []

    def _render(parent_id, indent=0):
        for t in by_parent.get(parent_id, []):
            if t["id"] not in include:
                continue
            prefix = "\t" * indent + "- "
            summary = f": {t['summary']}" if t["summary"] else ""
            lines.append(f"{prefix}{t['name']}{summary}")
            _render(t["id"], indent + 1)

    _render(None)
    return "\n".join(lines)


def get_topic_id(name):
    """Get topic ID by name, or None if not found."""
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM topics WHERE name = ?", (name,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def rename_topic(old_name, new_name):
    """Rename a topic. No-op if old_name doesn't exist or new_name already taken."""
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM topics WHERE name = ?", (old_name,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return
    cursor.execute("SELECT id FROM topics WHERE name = ?", (new_name,))
    if cursor.fetchone():
        conn.close()
        return
    cursor.execute("UPDATE topics SET name = ? WHERE name = ?", (new_name, old_name))
    conn.commit()
    conn.close()


def move_topic(name, new_parent_name):
    """Move a topic under a new parent (or to root if new_parent_name is None)."""
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM topics WHERE name = ?", (name,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return
    new_parent_id = None
    if new_parent_name:
        cursor.execute("SELECT id FROM topics WHERE name = ?", (new_parent_name,))
        parent_row = cursor.fetchone()
        if not parent_row:
            conn.close()
            return
        new_parent_id = parent_row[0]
    cursor.execute("UPDATE topics SET parent_id = ? WHERE name = ?", (new_parent_id, name))
    conn.commit()
    conn.close()


def insert_topic(name, parent_name=None, summary=None):
    """Insert a new topic. Returns its ID. Skips if already exists."""
    conn = _conn()
    cursor = conn.cursor()
    parent_id = None
    if parent_name:
        cursor.execute("SELECT id FROM topics WHERE name = ?", (parent_name,))
        row = cursor.fetchone()
        if row:
            parent_id = row[0]
    try:
        cursor.execute(
            "INSERT INTO topics (name, parent_id, summary) VALUES (?, ?, ?)",
            (name, parent_id, summary),
        )
        conn.commit()
        topic_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        cursor.execute("SELECT id FROM topics WHERE name = ?", (name,))
        topic_id = cursor.fetchone()[0]
    conn.close()
    return topic_id


def record_activity(topic_name, source, context, activity_date=None):
    """Record an activity entry for a topic."""
    topic_id = get_topic_id(topic_name)
    if not topic_id:
        topic_id = insert_topic(topic_name)
    conn = _conn()
    cursor = conn.cursor()
    if activity_date:
        cursor.execute(
            "INSERT INTO activity (topic_id, source, context, timestamp) VALUES (?, ?, ?, ?)",
            (topic_id, source, context, activity_date),
        )
    else:
        cursor.execute(
            "INSERT INTO activity (topic_id, source, context) VALUES (?, ?, ?)",
            (topic_id, source, context),
        )
    conn.commit()
    conn.close()


def get_topic_summary(name):
    """Get the current summary for a topic."""
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute("SELECT summary FROM topics WHERE name = ?", (name,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def update_topic_summary(name, summary):
    """Update a topic's summary."""
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute("UPDATE topics SET summary = ? WHERE name = ?", (summary, name))
    conn.commit()
    conn.close()


def generate_topics_file():
    """Write the full topic tree with summaries to TOPICS.md.

    Uses decay scoring to filter out stale topics from the output.
    """
    topics = get_topic_tree()
    scores = compute_decay_scores()
    active_count = sum(1 for t in topics if scores.get(t["id"], 0.0) >= DECAY_THRESHOLD)
    tree = format_topic_tree_for_output(topics, scores)
    name = config.get_user_name()
    output_path = config.get_topics_output_path()
    content = f"# {name}'s Topics\n*Updated: {datetime.now().strftime('%Y-%m-%d')}*\n\n{tree}\n"
    output_path.write_text(content)
    print(f"  Wrote {output_path} ({active_count} active / {len(topics)} total topics)")
    return topics
