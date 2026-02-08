#!/usr/bin/env python3
"""Clear the topics DB and re-seed with top-level categories.

Backs up the existing DB first, then drops all data and inserts fresh
root-level topic seeds with no summaries. Subtopics and summaries will
be created organically by the pipeline as it processes data.

Usage:
    mem reseed <instance-dir>              # interactive confirm
    mem reseed <instance-dir> --yes        # skip confirm
"""

import argparse
import shutil
import sqlite3
from datetime import datetime

from . import config


def reseed(skip_confirm=False):
    db_path = config.get_db_path()
    seed_topics = config.get_seed_topics()

    if not seed_topics:
        print("Error: no seed_topics defined in config.json")
        return

    if db_path.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = db_path.with_suffix(f".db.bak-{ts}")
        shutil.copy2(db_path, backup)
        print(f"Backed up to {backup.name}")

        if not skip_confirm:
            resp = input("This will DELETE all topics and activity. Continue? [y/N] ")
            if resp.lower() != "y":
                print("Aborted.")
                return
    else:
        print(f"No DB found at {db_path}, creating fresh.")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS activity")
    cur.execute("DROP TABLE IF EXISTS topics")
    cur.execute("""
        CREATE TABLE topics (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE,
            parent_id INTEGER REFERENCES topics(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            summary TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE activity (
            id INTEGER PRIMARY KEY,
            topic_id INTEGER REFERENCES topics(id),
            source TEXT,
            context TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    topic_ids = {}
    for name, parent in seed_topics:
        parent_id = topic_ids.get(parent) if parent else None
        cur.execute(
            "INSERT INTO topics (name, parent_id) VALUES (?, ?)",
            (name, parent_id),
        )
        topic_ids[name] = cur.lastrowid

    conn.commit()
    conn.close()
    names = [n for n, _ in seed_topics]
    print(f"Seeded {len(seed_topics)} topics: {', '.join(names)}")
