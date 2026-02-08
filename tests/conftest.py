"""Shared fixtures for mem tests."""

import json
import sqlite3
import pytest
from pathlib import Path
from datetime import datetime, timedelta

from pipeline import config


@pytest.fixture(autouse=True)
def instance_dir(tmp_path):
    """Create a minimal instance dir and init config for every test."""
    cfg = {"name": "Test", "collectors": [], "plugins": [], "llm": {"backend": "claude"}}
    (tmp_path / "config.json").write_text(json.dumps(cfg))
    (tmp_path / "bio.md").write_text("Test user.")
    (tmp_path / "debug").mkdir()
    config.init(tmp_path)
    _init_db(tmp_path / "topics.db")
    return tmp_path


def _init_db(db_path):
    """Create empty topics + activity tables."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE,
            parent_id INTEGER REFERENCES topics(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            summary TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY,
            topic_id INTEGER REFERENCES topics(id),
            source TEXT,
            context TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def seed_topics(topics):
    """Insert topics into the DB. Each item is (name, parent_name_or_None, summary_or_None)."""
    from pipeline.topic_db import insert_topic, update_topic_summary
    for name, parent, summary in topics:
        insert_topic(name, parent_name=parent, summary=summary)
        if summary:
            update_topic_summary(name, summary)


def add_activity(topic_name, days_ago=0, source="test"):
    """Record activity for a topic at a specific time."""
    from pipeline.topic_db import record_activity
    ts = (datetime.now() - timedelta(days=days_ago)).isoformat()
    record_activity(topic_name, source, "test activity", activity_date=ts)
