"""Claude Code conversation history collector - noise-filtered item lists."""

import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'lib'))

from claude_history import (
    CLAUDE_PROJECTS_DIR,
    decode_project_path,
    extract_content,
    get_current_project_encoded,
)
from .shared import format_time_range
from .base import Collector
from .. import config

# Previews matching these are noise, not meaningful session content
TRIVIAL_PREVIEWS = {
    "[tool result]",
    "[tool:",
    "You are maintaining a personal knowledge profile",
    "You are building a personal knowledge profile",
    "Warmup",
    "<local-command-caveat>",
}

# Topics that are too generic to match by name words alone
SKIP_TOPICS = {"people", "social", "travel", "home", "job", "health"}

# Minimum word length to consider significant
MIN_WORD_LEN = 4

STOPWORDS = frozenset({
    "a", "about", "above", "after", "again", "against", "all", "also", "am", "an",
    "and", "any", "are", "aren", "arent", "as", "at", "be", "because", "been",
    "before", "being", "below", "between", "both", "but", "by", "can", "could",
    "did", "didn", "do", "does", "doesn", "doing", "don", "dont", "down", "during",
    "each", "even", "every", "few", "for", "from", "further", "get", "gets", "got",
    "had", "hadn", "has", "hasn", "have", "haven", "having", "her", "here", "hers",
    "herself", "him", "himself", "his", "how", "however", "if", "in", "into", "is",
    "isn", "it", "its", "itself", "just", "know", "let", "like", "ll", "look",
    "make", "may", "me", "might", "more", "most", "much", "must", "my", "myself",
    "need", "new", "nor", "not", "now", "of", "off", "on", "once", "only", "or",
    "other", "our", "ours", "ourselves", "out", "over", "own", "re", "really",
    "right", "said", "same", "shan", "she", "should", "shouldn", "so", "some",
    "something", "still", "such", "take", "than", "that", "the", "their", "theirs",
    "them", "themselves", "then", "there", "these", "they", "thing", "things",
    "think", "this", "those", "through", "to", "too", "under", "until", "up",
    "upon", "use", "used", "using", "very", "want", "was", "wasn", "we", "well",
    "were", "weren", "what", "when", "where", "which", "while", "who", "whom",
    "why", "will", "with", "without", "won", "wont", "would", "wouldn", "you",
    "your", "yours", "yourself",
    # tech-generic words
    "app", "code", "file", "project", "working", "build", "update", "change",
    "changes", "work", "help", "check", "please", "thanks", "good", "great",
    "sure", "yeah", "yes", "okay", "start", "stop", "run", "test", "data",
    "set", "line", "type", "name", "list", "based", "made", "making", "goes",
    "going", "come", "back", "open", "close", "read", "write", "find",
    "time", "long", "first", "last", "next", "keep", "give", "call",
    "tool", "tools", "user", "system", "service", "active", "current",
})


def _get_user_stopwords():
    """Get user-specific stopwords from config."""
    return frozenset(w.lower() for w in config.get_stopwords())


def _build_topic_patterns(topics):
    """Build regex patterns from topic name words only (not summaries)."""
    patterns = {}
    for t in topics:
        if t["name"] in SKIP_TOPICS:
            continue
        words = [w for w in t["name"].split("-") if len(w) >= MIN_WORD_LEN and w not in STOPWORDS]
        if words:
            regex = "|".join(re.escape(w) for w in words)
            patterns[t["name"]] = re.compile(rf"\b(?:{regex})\b", re.IGNORECASE)
    return patterns


def _get_session_text(session_file):
    """Extract all text from a session JSONL. Returns (full_text, first_user_message)."""
    parts = []
    first_user = None
    try:
        with open(session_file) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    msg = entry.get("message", {})
                    content = msg.get("content", "")
                    extracted = extract_content(content)
                    if extracted:
                        parts.append(extracted)
                        if not first_user and (
                            entry.get("type") == "user" or msg.get("role") == "user"
                        ):
                            first_user = extracted.replace("\n", " ")
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    return " ".join(parts), first_user or ""


def _is_trivial(preview):
    if not preview:
        return True
    return any(t and preview.startswith(t) for t in TRIVIAL_PREVIEWS)


class ClaudeCodeCollector(Collector):
    name = "claude"
    description = "Claude Code conversation history"

    def collect(self, since_dt, until_dt=None):
        if not CLAUDE_PROJECTS_DIR.exists():
            return None

        from ..topic_db import get_topic_tree

        current = get_current_project_encoded()
        topics = get_topic_tree()
        patterns = _build_topic_patterns(topics)
        user_stopwords = _get_user_stopwords()

        sessions = []
        for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
            if not project_dir.is_dir():
                continue
            decoded = decode_project_path(project_dir.name)
            is_current = current and project_dir.name == current
            session_files = sorted(
                project_dir.glob("*.jsonl"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for i, sf in enumerate(session_files):
                if is_current and i == 0:
                    continue
                mtime = datetime.fromtimestamp(sf.stat().st_mtime)
                if since_dt and mtime < since_dt:
                    continue
                if until_dt and mtime >= until_dt:
                    continue

                text, preview = _get_session_text(sf)
                if _is_trivial(preview):
                    continue

                matched = [name for name, pat in patterns.items() if pat.search(text)]
                sessions.append({
                    "mtime": mtime,
                    "preview": preview,
                    "topics": matched,
                    "project": decoded.rstrip("/"),
                })

        if not sessions:
            return None

        sessions.sort(key=lambda s: s["mtime"], reverse=True)

        by_project = defaultdict(list)
        for s in sessions:
            by_project[s["project"]].append(s)

        lines = [f"# Claude Code ({format_time_range(since_dt)})"]
        for name, slist in sorted(by_project.items(), key=lambda x: -len(x[1])):
            lines.append(f"\n## {name}")
            for s in slist:
                preview = s["preview"][:1000]
                lines.append(f"- [{s['mtime'].strftime('%m/%d %H:%M')}] \"{preview}\"")

        return "\n".join(lines)
