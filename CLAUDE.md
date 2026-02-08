# mem

Generic hierarchical topic summarizer. Ingests unstructured text, routes to topic hierarchies via LLM, maintains decay-scored summaries, outputs a continuously-updated context document.

## Architecture

| File | Purpose |
|------|---------|
| `bin/mem` | CLI entry point (`init`, `run`, `reseed`, `upgrade`) |
| `pipeline/config.py` | Instance dir loader, all path resolution |
| `pipeline/topic_db.py` | SQLite (topics tree + activity log), decay scoring (14-day half-life) |
| `pipeline/topics_route.py` | LLM routing prompt, JSON parsing |
| `pipeline/topics_context.py` | Per-topic LLM summarization |
| `pipeline/topics_pipeline.py` | Full pipeline: ingest → route → contextualize → MEMORY.md |
| `pipeline/ollama_client.py` | LLM client (Claude CLI default, Ollama backup) |
| `pipeline/actions.py` | Action plugin system (piggybacks on routing LLM call) |
| `pipeline/mem_init.py` | Interactive `mem init` setup flow |
| `pipeline/reseed_topics.py` | Clear and re-seed topics DB |
| `pipeline/ingest/` | Built-in macOS collectors (browser, texts, calls, claude, calendar, email, reminders) |
| `tools/` | CLI query tools (texts, contacts, email, calendar, claude_history, browser_history, topics) |
| `lib/` | Shared utilities (imessage, contacts, browser_db, google_auth) |
| `actions/auto-calendar/` | Built-in action for scheduling detection |
| `examples/` | Example collector plugins |

## Running the Pipeline

Pipeline MUST run with `dangerouslyDisableSandbox: true` (filesystem access for OAuth tokens, Claude CLI makes network calls).

```bash
# Via CLI
mem run <instance_dir>
mem run <instance_dir> --date 2026-02-06      # specific date
mem run <instance_dir> --source browser        # single source
mem run <instance_dir> --dry-run               # ingestion only, no LLM
```

## When to Run `mem upgrade`

`mem upgrade <dir>` reinstalls tool wrappers in the instance directory and optionally updates the launchd schedule. Run it when:

- **New tool added** to `tools/` — wrappers won't exist for it until upgrade runs
- **Tool renamed or deleted** — old wrappers will point to missing files
- **Wrapper format changed** in `cmd_upgrade` (e.g. new env vars added) — existing wrappers use the old format

You do NOT need to run upgrade when:
- Pipeline code changes (`pipeline/*.py`) — picked up automatically by `mem run`
- Routing prompt changes — picked up automatically
- LLM backend changes in config.json — picked up automatically
- Collector changes (`pipeline/ingest/`) — picked up automatically

## Key Design Decisions

- Instance directory pattern: per-user/per-project config, bio, DB, output
- Routing prompt is generic — `bio.md` provides all context
- Tool wrappers live in the instance dir, set `MEM_INSTANCE_DIR` env var
- Topic names use spaces, not dashes
- `config.init(instance_dir)` must be called before any DB/config access
- Default output file: `MEMORY.md` (configurable via `topics_output` in config.json)

## Testing

No test suite yet. To manually verify:

```bash
# Tools work
<instance_dir>/<name>-topics --short
<instance_dir>/<name>-topics music              # subtree
<instance_dir>/<name>-contacts --help

# Pipeline runs
mem run <instance_dir> --dry-run --source browser

# Schedule is loaded
launchctl list | grep mem-update
```

## Sam's Instance

Instance dir: `~/code/brain/memory/`
Output: `~/code/brain/MEMORY.md` (imported into brain's CLAUDE.md via `@MEMORY.md`)
Schedule: `com.sam.mem-update` — daily at 00:01
