"""Instance directory loader — all path resolution goes through here."""

import json
import os
import subprocess
from pathlib import Path

_instance_dir = None  # Set once at startup


def init(instance_dir: Path):
    """Called by CLI to set the active instance directory."""
    global _instance_dir
    _instance_dir = Path(instance_dir).resolve()


def get_instance_dir() -> Path:
    if _instance_dir is None:
        raise RuntimeError("config.init() must be called before accessing instance dir")
    return _instance_dir


def load_config() -> dict:
    return json.loads((get_instance_dir() / "config.json").read_text())


def get_user_name() -> str:
    return load_config()["name"]


def get_user_bio() -> str:
    return (get_instance_dir() / "bio.md").read_text().strip()


def get_db_path() -> Path:
    return get_instance_dir() / "topics.db"


def get_debug_dir() -> Path:
    d = get_instance_dir() / "debug"
    d.mkdir(exist_ok=True)
    return d


def get_topics_output_path() -> Path:
    cfg = load_config()
    if "topics_output" in cfg:
        return Path(os.path.expanduser(cfg["topics_output"]))
    return get_instance_dir() / "TOPICS.md"


def get_watermark_path() -> Path:
    return get_instance_dir() / ".last_run"


def get_kept_state_path() -> Path:
    return get_instance_dir() / "kept_email_ids.json"


def get_collectors() -> list[str]:
    return load_config().get("collectors", [])


def get_plugins() -> list[dict]:
    return load_config().get("plugins", [])


def get_llm_backend() -> str:
    return load_config().get("llm", {}).get("backend", "claude")


def get_seed_topics() -> list[tuple[str, str | None]]:
    """Load seed topics from config. Returns list of (name, parent_or_None)."""
    cfg = load_config()
    seeds = cfg.get("seed_topics", [])
    result = []
    for item in seeds:
        if isinstance(item, str):
            result.append((item, None))
        elif isinstance(item, dict):
            result.append((item["name"], item.get("parent")))
    return result


def get_stopwords() -> list[str]:
    """User-specific stopwords for Claude Code collector."""
    cfg = load_config()
    name = cfg.get("name", "").lower()
    extra = cfg.get("stopwords", [])
    words = [w for w in name.split() if w]
    words.extend(extra)
    return words


def render_template(text: str) -> str:
    """Replace {user} and {user_bio} in prompt templates."""
    text = text.replace("{user}", get_user_name())
    text = text.replace("{user_bio}", get_user_bio())
    return text


def notify(message: str):
    """Send a notification via the user's configured notify_command. No-op if not set."""
    cmd = load_config().get("notify_command")
    if not cmd:
        return
    cmd = os.path.expanduser(cmd)
    try:
        subprocess.run(cmd, input=message, text=True, timeout=30, shell=True)
    except Exception as e:
        print(f"  Notification failed: {e}")
