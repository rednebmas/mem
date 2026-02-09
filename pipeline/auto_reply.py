"""Auto-reply: detect unanswered texts and send draft replies via Telegram.

For each flagged person:
1. Pull the full recent conversation via TextsSource
2. Include Sam's calendar for scheduling context
3. Ask LLM to draft a reply in Sam's voice
4. Send the draft to Sam via Telegram for approval
"""

import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

from . import config
from .llm import generate
from .ingest.texts import TextsSource
from .ingest.calendar_events import _fetch_events, _format_event_time

# Track recently flagged persons to avoid re-flagging on consecutive runs
_SEEN_STATE_KEY = "auto_reply_seen"


DRAFT_PROMPT = """You are {user}. Draft a short, natural text message reply to this conversation.

Today is {{today}} ({{day_of_week}}).

Conversation with {{person}} (last 7 days):
---
{{thread}}
---

{user}'s calendar (next 7 days):
---
{{calendar}}
---

Rules:
- Write ONLY the reply text, nothing else
- Match {user}'s texting style from the conversation (casual, concise)
- If the message involves scheduling, reference the calendar to suggest times
- Keep it brief — this is a text message, not an email
- If you genuinely cannot draft a useful reply, respond with exactly: SKIP"""


def _log(label, content):
    """Write debug log."""
    debug_dir = config.get_debug_dir()
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = debug_dir / f"{ts}_autoreply_{label}.md"
    path.write_text(content)
    print(f"    Debug log: {path}")


def _extract_person_thread(texts_output, person):
    """Extract a single person's thread from grouped texts output."""
    lines = texts_output.split("\n")
    collecting = False
    thread_lines = []
    for line in lines:
        if line and not line.startswith(" ") and not line.startswith("#"):
            if person.lower() in line.lower() and "messages):" in line:
                collecting = True
                thread_lines.append(line)
            elif collecting:
                break
        elif collecting:
            thread_lines.append(line)
    return "\n".join(thread_lines) if thread_lines else None


def _format_calendar(events):
    """Format upcoming calendar events for context."""
    if not events:
        return "(no upcoming events)"
    lines = []
    for event in events:
        summary = event.get("summary", "(No title)")
        time_str = _format_event_time(event)
        line = f'- "{summary}" ({time_str})'
        loc = event.get("location", "")
        if loc:
            line += f" @ {loc}"
        lines.append(line)
    return "\n".join(lines)


def _find_telegram_tool():
    """Find the sam-telegram CLI tool."""
    name = config.get_user_name().lower()
    for candidate in [f"{name}-telegram", "mem-telegram"]:
        path = shutil.which(candidate)
        if path:
            return path
    mem_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(mem_dir, "tools", "telegram")


def _load_seen():
    """Load set of recently notified person names."""
    state_path = config.get_instance_dir() / "auto_reply_seen.json"
    if state_path.exists():
        data = json.loads(state_path.read_text())
        # Expire entries older than 24 hours
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        return {k: v for k, v in data.items() if v > cutoff}
    return {}


def _save_seen(seen):
    """Save recently notified person names."""
    state_path = config.get_instance_dir() / "auto_reply_seen.json"
    state_path.write_text(json.dumps(seen, indent=2))


def draft_reply(person, flag_context=""):
    """Pull full conversation, draft a reply via LLM, send to Sam via Telegram."""
    print(f"\n  Drafting reply for {person}...")

    texts_source = TextsSource()
    since_dt = datetime.now() - timedelta(days=7)
    texts_output = texts_source.collect(since_dt)
    if not texts_output:
        print(f"    No texts found")
        _log(f"{person}_no_texts", f"# Auto-Reply: {person}\n\nNo texts found.\n")
        return None

    thread = _extract_person_thread(texts_output, person)
    if not thread:
        print(f"    No conversation found with {person}")
        _log(f"{person}_no_thread", (
            f"# Auto-Reply: {person}\n\n"
            f"No thread found. Flag context: {flag_context}\n"
        ))
        return None

    # Get calendar context
    now = datetime.now(timezone.utc)
    events = _fetch_events(now, now + timedelta(days=7))
    calendar_text = _format_calendar(events)

    today = datetime.now()
    rendered_prompt = config.render_template(DRAFT_PROMPT)
    prompt = rendered_prompt.format(
        today=today.strftime("%Y-%m-%d"),
        day_of_week=today.strftime("%A"),
        person=person,
        thread=thread,
        calendar=calendar_text,
    )

    print(f"    Generating draft...")
    draft = generate(prompt).strip()

    _log(f"{person}_draft", (
        f"# Auto-Reply Draft: {person}\n\n"
        f"## Flag context\n{flag_context}\n\n"
        f"## Prompt\n\n{prompt}\n\n"
        f"## Draft\n\n{draft}\n"
    ))

    if draft == "SKIP":
        print(f"    LLM chose to skip (no useful reply possible)")
        return None

    return draft


def _send_draft_to_telegram(person, draft):
    """Send draft reply to Sam via Telegram for approval."""
    telegram_tool = _find_telegram_tool()
    message = (
        f"<b>Draft reply to {person}:</b>\n"
        f"<i>{draft}</i>\n\n"
        f"Reply with edits or 👍 to send"
    )
    try:
        result = subprocess.run(
            [telegram_tool, "--html", message],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            print(f"    Sent draft to Telegram")
        else:
            print(f"    Telegram send failed: {result.stderr[:200]}")
    except Exception as e:
        print(f"    Telegram send error: {e}")
        # Fall back to notify
        config.notify(f"Draft reply to {person}: {draft}")


def process_unanswered_flags(flags):
    """Process unanswered text flags from the routing LLM response."""
    seen = _load_seen()

    # Deduplicate
    unique_flags = []
    seen_persons = set()
    for flag in flags:
        person = flag.get("person", "")
        if person and person not in seen_persons:
            seen_persons.add(person)
            unique_flags.append(flag)

    _log("flags_received", (
        f"# Auto-Reply Flags Received\n\n"
        f"**Raw flags:** {len(flags)}\n"
        f"**Unique persons:** {len(unique_flags)}\n\n"
        + "\n".join(f"- **{f.get('person')}**: {f.get('context')}" for f in unique_flags)
        + "\n"
    ))

    print(f"\n=== Auto-Reply: {len(unique_flags)} unanswered conversation(s) flagged ===")
    drafts_sent = 0

    for flag in unique_flags:
        person = flag["person"]
        context = flag.get("context", "")

        # Skip if we recently notified about this person
        if person in seen:
            print(f"  {person}: skipped (already notified recently)")
            continue

        print(f"  {person}: {context}")
        draft = draft_reply(person, flag_context=context)

        if draft:
            _send_draft_to_telegram(person, draft)
            seen[person] = datetime.now(timezone.utc).isoformat()
            drafts_sent += 1

    _save_seen(seen)

    if drafts_sent:
        print(f"\n  Total: {drafts_sent} draft(s) sent to Telegram")
    else:
        print(f"\n  No drafts sent")

    return drafts_sent
