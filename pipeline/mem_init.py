"""Guided setup flow for creating a new mem instance."""

import json
import sqlite3
from pathlib import Path

from . import config


def guided_init(instance_dir: Path):
    """Interactive setup that creates an instance directory with config + bio + seeded DB."""
    print(f"Creating mem instance at {instance_dir}\n")

    if (instance_dir / "config.json").exists():
        print(f"Instance already exists at {instance_dir}")
        print("To re-initialize, delete the directory first.")
        return

    # Gather identity
    name = input("Your first name: ").strip()
    if not name:
        print("Name is required.")
        return

    city = input("City (e.g., Seattle, WA): ").strip()
    job = input("Job title and company (e.g., Software Engineer at Stripe): ").strip()
    interests = input("Interests (comma-separated, e.g., skiing, cooking, AI): ").strip()

    # Build bio
    bio_parts = [f"{name}"]
    if city:
        bio_parts[0] += f", based in {city}."
    else:
        bio_parts[0] += "."
    if job:
        bio_parts.append(f"{job}.")
    if interests:
        bio_parts.append(f"Interests: {interests}.")
    bio = " ".join(bio_parts)

    print(f"\nBio: {bio}")
    print("(You can edit bio.md later to refine this.)\n")

    # Gather seed topics
    print("Enter at least 3 top-level topics (comma-separated).")
    print("These are the broad categories of your life that mem will organize around.")
    print("Examples: work, health, home, hobbies, social, finance, travel\n")
    topics_input = input("Topics: ").strip()
    if not topics_input:
        print("At least 3 topics are required.")
        return

    topic_names = [t.strip() for t in topics_input.split(",") if t.strip()]
    if len(topic_names) < 3:
        print(f"Need at least 3 topics, got {len(topic_names)}.")
        return

    # Always add "people" under "social" if social exists
    seed_topics = [(t, None) for t in topic_names]
    if "social" in topic_names:
        seed_topics.append(("people", "social"))
        print("(Added 'people' as a subtopic of 'social' — for tracking relationships)")

    print(f"\nTopics: {', '.join(t[0] for t in seed_topics)}")

    # Choose collectors
    print("\nAvailable collectors (macOS):")
    print("  browser    - Chrome/Safari history")
    print("  texts      - iMessage conversations")
    print("  calls      - Phone call history")
    print("  claude     - Claude Code sessions")
    print("  calendar   - Google Calendar events")
    print("  email      - Gmail threads")
    print("  reminders  - Apple Reminders")
    print()
    collectors_input = input("Collectors to enable (comma-separated, or 'all'): ").strip()
    if collectors_input.lower() == "all":
        collectors = ["browser", "texts", "calls", "claude", "calendar", "email", "reminders"]
    else:
        collectors = [c.strip() for c in collectors_input.split(",") if c.strip()]

    # Choose LLM backend
    print("\nLLM backend:")
    print("  claude  - Claude CLI (requires 'claude' command)")
    print("  ollama  - Local Ollama (requires 'ollama serve' + model)")
    backend = input("Backend [claude]: ").strip() or "claude"

    # Create instance directory
    instance_dir.mkdir(parents=True, exist_ok=True)

    # Write config.json
    cfg = {
        "name": name,
        "collectors": collectors,
        "plugins": [],
        "llm": {"backend": backend},
        "seed_topics": [
            {"name": n, "parent": p} if p else n
            for n, p in seed_topics
        ],
    }
    (instance_dir / "config.json").write_text(json.dumps(cfg, indent=2) + "\n")
    print(f"\nWrote {instance_dir / 'config.json'}")

    # Write bio.md
    (instance_dir / "bio.md").write_text(bio + "\n")
    print(f"Wrote {instance_dir / 'bio.md'}")

    # Create debug dir
    (instance_dir / "debug").mkdir(exist_ok=True)

    # Seed topics DB
    config.init(instance_dir)
    db_path = config.get_db_path()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE,
            parent_id INTEGER REFERENCES topics(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            summary TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY,
            topic_id INTEGER REFERENCES topics(id),
            source TEXT,
            context TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    topic_ids = {}
    for name_t, parent in seed_topics:
        parent_id = topic_ids.get(parent) if parent else None
        cur.execute("INSERT INTO topics (name, parent_id) VALUES (?, ?)", (name_t, parent_id))
        topic_ids[name_t] = cur.lastrowid
    conn.commit()
    conn.close()
    print(f"Seeded {len(seed_topics)} topics in {db_path}")

    print(f"\nInstance ready at {instance_dir}")
    print(f"\nNext steps:")
    print(f"  mem run {instance_dir} --dry-run    # Test ingestion")
    print(f"  mem run {instance_dir}              # Full pipeline run")
    if "email" in collectors or "calendar" in collectors:
        print(f"\nFor email/calendar, place your Google OAuth credentials at:")
        print(f"  {instance_dir / 'google_oauth.json'}")
