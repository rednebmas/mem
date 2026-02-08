# 🧠 mem

A personal knowledge system that builds topic hierarchies from your digital life — so your AI assistant can give deeply personalized responses instead of generic ones.

## How It Works

mem ingests data from your personal sources (browser history, texts, emails, calendar, etc.), routes items to topic hierarchies via LLM, and maintains per-topic summaries. The output is a continuously-updated `TOPICS.md` that represents your current life context.

```
Data Sources (browser, texts, email, calendar, calls, reminders, claude)
    ↓ noise-filtered
Topic Routing + Summarization (LLM)
    ↓
Topic Hierarchies (SQLite) → TOPICS.md
```

## Quickstart

```bash
git clone <repo-url> ~/code/mem
cd ~/code/mem
./setup.sh
mem init ~/mem-personal
mem run ~/mem-personal --dry-run   # test ingestion
mem run ~/mem-personal             # full pipeline
```

## Concepts

**Instance directory** — A folder containing your config, bio, topic database, and output. You can have multiple instances (personal, work, etc.) with different configurations.

**Collectors** — Built-in data source adapters (browser, texts, email, etc.). macOS-only collectors are skipped on other platforms.

**Plugins** — External scripts that extend mem with custom data sources. Any executable that prints markdown to stdout.

**Actions** — Optional post-processing that piggybacks on the single routing LLM call for free detection. Actions add detection prompts to the routing call and receive structured flags, then dispatch to handlers that can make their own LLM calls, hit APIs, or send notifications. See [docs/actions.md](docs/actions.md).

## Instance Directory

Created by `mem init`:

```
~/mem-personal/
├── config.json          # Collectors, actions, LLM backend, plugins
├── bio.md               # Your bio (inserted into LLM prompts)
├── topics.db            # SQLite topic tree + activity log
├── TOPICS.md            # Generated output
├── debug/               # LLM prompt/response logs
├── .last_run            # Watermark for incremental processing
├── google_oauth.json    # GCP OAuth credentials (if using email/calendar)
└── google_token.json    # OAuth token (auto-generated)
```

## Adding a Plugin

Create any executable script that takes two args (`<since_iso> <until_iso>`) and prints markdown to stdout:

```python
#!/usr/bin/env python3
"""Collect recent Jira tickets."""
import sys
since = sys.argv[1]  # ISO datetime
until = sys.argv[2]
# ... query your data source ...
print("# Jira\n- PROJ-123: Fix login bug (In Progress)")
```

Add it to `config.json`:

```json
{
  "plugins": [
    {"name": "jira", "command": "~/work/mem-plugins/jira-collector.py"}
  ]
}
```

## CLI Tools

`mem install-tools <dir>` creates `{name}-*` symlinks:

| Tool | Description |
|------|-------------|
| `{name}-texts` | iMessage history |
| `{name}-contacts` | macOS Contacts search |
| `{name}-email` | Gmail messages |
| `{name}-calendar` | Calendar events |
| `{name}-claude_history` | Claude Code history |
| `{name}-browser_history` | Browser history |

## Requirements

- Python 3.11+
- macOS (for iMessage, Contacts, Reminders, Call History collectors)
- Claude CLI or Ollama (for LLM backend)
- Google OAuth credentials (for email/calendar)
