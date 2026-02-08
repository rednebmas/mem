"""Auto-calendar: validate flagged scheduling conversations and create events.

Supports three event states:
- **create**: Confirmed plans → regular calendar event
- **hold**: Proposed-but-unconfirmed plans → [HOLD] prefixed event
- **confirm_hold**: Confirmation of a previous hold → removes [HOLD] prefix
- **delete**: Cancellations → removes event

Holds auto-expire after 2 days or 1 hour before event start.
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from . import config
from .ollama_client import generate
from .ingest.texts import TextsSource
from .ingest.calendar_events import CalendarSource, _fetch_events, _format_event_time

HOLD_PREFIX = "[HOLD] "
HOLD_EXPIRY_DAYS = 2
HOLD_EXPIRY_HOURS_BEFORE_START = 1


VALIDATION_PROMPT = """You are {user}'s calendar assistant. Analyze this text conversation and determine if any calendar events should be created, held, confirmed, or deleted.

Today is {{today}} ({{day_of_week}}).

Conversation with {{person}} (last 7 days):
---
{{thread}}
---

{user}'s existing calendar (next 14 days):
---
{{calendar}}
---

Active holds (proposed but unconfirmed):
---
{{holds}}
---

Rules:
- "create": Both people agreed on a specific date/time. Create a confirmed event.
- "hold": {user} or the other person PROPOSED a specific date/time, but the other hasn't confirmed yet. Creates a tentative [HOLD] event. Only use when a concrete time was mentioned (not vague "let's hang soon").
- "confirm_hold": The conversation confirms a previously held event (shown in active holds above). Provide the hold's title so it can be promoted to confirmed.
- "delete": Plans were cancelled. Provide the event title to remove.
- Do NOT create/hold events that already exist on the calendar (check both calendar and holds)
- Do NOT create/hold events for past dates
- Resolve relative dates ("Thursday") to the next upcoming one from today
- Include the person's name in the title (e.g., "Dinner with Craig")
- Duration defaults to 1h if not mentioned

Return ONLY valid JSON:
{{{{"events": [
  {{{{"action": "create", "title": "Event Title", "start": "YYYY-MM-DD HH:MM", "duration": "1h", "location": "optional or null"}}}},
  {{{{"action": "hold", "title": "Event Title", "start": "YYYY-MM-DD HH:MM", "duration": "1h", "location": "optional or null"}}}},
  {{{{"action": "confirm_hold", "title": "[HOLD] Event Title"}}}},
  {{{{"action": "delete", "title": "Event to remove"}}}}
]}}}}"""


def _log(label, content):
    """Write debug log."""
    debug_dir = config.get_debug_dir()
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = debug_dir / f"{ts}_autocal_{label}.md"
    path.write_text(content)
    print(f"    Debug log: {path}")


def _find_calendar_tool():
    """Find the calendar CLI tool. Checks for {name}-calendar symlink or mem tools/calendar."""
    name = config.get_user_name().lower()
    for candidate in [f"{name}-calendar", "mem-calendar"]:
        path = shutil.which(candidate)
        if path:
            return path
    # Fall back to tools/calendar in the mem repo
    mem_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(mem_dir, "tools", "calendar")


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


def _format_calendar_events(events):
    """Format calendar events for the validation prompt (excludes holds)."""
    regular = [e for e in events if not e.get("summary", "").startswith(HOLD_PREFIX)]
    if not regular:
        return "(no events)"
    lines = []
    for event in regular:
        summary = event.get("summary", "(No title)")
        time_str = _format_event_time(event)
        line = f'- "{summary}" ({time_str})'
        loc = event.get("location", "")
        if loc:
            line += f" @ {loc}"
        lines.append(line)
    return "\n".join(lines)


def _format_hold_events(events):
    """Format active [HOLD] events for the validation prompt."""
    holds = [e for e in events if e.get("summary", "").startswith(HOLD_PREFIX)]
    if not holds:
        return "(no active holds)"
    lines = []
    for event in holds:
        summary = event.get("summary", "")
        time_str = _format_event_time(event)
        created = event.get("created", "")
        line = f'- "{summary}" ({time_str}, created {created[:10]})'
        lines.append(line)
    return "\n".join(lines)


def _parse_json(text):
    """Extract JSON from LLM response."""
    text = text.strip()
    if "```json" in text:
        parts = text.split("```json")
        last_block = parts[-1]
        if "```" in last_block:
            last_block = last_block.split("```")[0]
        return json.loads(last_block.strip())
    if "```" in text:
        blocks = text.split("```")
        for i in range(len(blocks) - 2, 0, -2):
            candidate = blocks[i].strip()
            if candidate.startswith("{"):
                return json.loads(candidate)
    return json.loads(text)


def validate_and_create(person, flag_context=""):
    """Pull full conversation, validate with LLM, create/delete events."""
    print(f"\n  Processing scheduling with {person}...")

    texts_source = TextsSource()
    since_dt = datetime.now() - timedelta(days=7)
    texts_output = texts_source.collect(since_dt)
    if not texts_output:
        print(f"    No texts found")
        _log(f"{person}_no_texts", f"# Auto-Calendar: {person}\n\nNo texts found in last 7 days.\n")
        return []

    thread = _extract_person_thread(texts_output, person)
    if not thread:
        print(f"    No conversation found with {person}")
        _log(f"{person}_no_thread", (
            f"# Auto-Calendar: {person}\n\n"
            f"No conversation thread found for '{person}'.\n\n"
            f"## Flag context\n{flag_context}\n\n"
            f"## Available conversations in texts output\n```\n"
            + "\n".join(l for l in texts_output.split("\n") if "messages):" in l)
            + "\n```\n"
        ))
        return []

    now = datetime.now(timezone.utc)
    events = _fetch_events(now, now + timedelta(days=14))
    calendar_text = _format_calendar_events(events)
    holds_text = _format_hold_events(events)

    today = datetime.now()
    rendered_prompt = config.render_template(VALIDATION_PROMPT)
    prompt = rendered_prompt.format(
        today=today.strftime("%Y-%m-%d"),
        day_of_week=today.strftime("%A"),
        person=person,
        thread=thread,
        calendar=calendar_text,
        holds=holds_text,
    )

    print(f"    Validating with LLM...")
    raw = generate(prompt)

    _log(f"{person}_validation", (
        f"# Auto-Calendar Validation: {person}\n\n"
        f"## Flag context\n{flag_context}\n\n"
        f"## Prompt\n\n{prompt}\n\n"
        f"## LLM Response\n\n{raw}\n"
    ))

    try:
        result = _parse_json(raw)
    except json.JSONDecodeError:
        print(f"    Warning: JSON parse error, retrying...")
        raw = generate(prompt)
        _log(f"{person}_validation_retry", (
            f"# Auto-Calendar Validation Retry: {person}\n\n"
            f"## Prompt\n\n{prompt}\n\n"
            f"## LLM Response\n\n{raw}\n"
        ))
        try:
            result = _parse_json(raw)
        except json.JSONDecodeError:
            print(f"    Warning: JSON parse failed after retry, skipping {person}")
            return []

    actions = []
    cal_tool = _find_calendar_tool()

    for event in result.get("events", []):
        action = event.get("action")
        title = event.get("title")
        if not title:
            continue

        if action == "create":
            start = event.get("start")
            if not start:
                continue
            cmd = [cal_tool, "--add", title, "--start", start]
            duration = event.get("duration")
            if duration:
                cmd += ["--duration", duration]
            location = event.get("location")
            if location and location != "null":
                cmd += ["--location", location]
            print(f"    Creating: {title} at {start}")
            cal_result = subprocess.run(cmd, capture_output=True, text=True)
            _log(f"{person}_create_{title.replace(' ', '_')[:20]}", (
                f"# Calendar Create: {title}\n\n"
                f"**Command:** {' '.join(cmd)}\n\n"
                f"**stdout:** {cal_result.stdout}\n"
                f"**stderr:** {cal_result.stderr}\n"
                f"**returncode:** {cal_result.returncode}\n"
            ))
            actions.append({"action": "create", "title": title, "start": start})
            config.notify(f"📅 Created: {title} ({start})")

        elif action == "hold":
            start = event.get("start")
            if not start:
                continue
            hold_title = f"{HOLD_PREFIX}{title}"
            existing_holds = [e for e in _fetch_events(now, now + timedelta(days=14))
                              if e.get("summary", "").startswith(HOLD_PREFIX)
                              and person.lower().split()[0].lower() in e.get("summary", "").lower()]
            if existing_holds:
                print(f"    Hold already exists for {person}, skipping: {hold_title}")
                continue
            cmd = [cal_tool, "--add", hold_title, "--start", start]
            duration = event.get("duration")
            if duration:
                cmd += ["--duration", duration]
            location = event.get("location")
            if location and location != "null":
                cmd += ["--location", location]
            print(f"    Holding: {hold_title} at {start}")
            cal_result = subprocess.run(cmd, capture_output=True, text=True)
            _log(f"{person}_hold_{title.replace(' ', '_')[:20]}", (
                f"# Calendar Hold: {hold_title}\n\n"
                f"**Command:** {' '.join(cmd)}\n\n"
                f"**stdout:** {cal_result.stdout}\n"
                f"**stderr:** {cal_result.stderr}\n"
                f"**returncode:** {cal_result.returncode}\n"
            ))
            actions.append({"action": "hold", "title": hold_title, "start": start})
            config.notify(f"⏳ Hold: {title} ({start}) — awaiting confirmation")

        elif action == "confirm_hold":
            hold_title = title if title.startswith(HOLD_PREFIX) else f"{HOLD_PREFIX}{title}"
            confirmed_title = hold_title.replace(HOLD_PREFIX, "", 1)
            cmd = [cal_tool, "--patch", hold_title, "--new-title", confirmed_title]
            print(f"    Confirming hold: {hold_title} → {confirmed_title}")
            cal_result = subprocess.run(cmd, capture_output=True, text=True)
            _log(f"{person}_confirm_{title.replace(' ', '_')[:20]}", (
                f"# Calendar Confirm Hold: {hold_title} → {confirmed_title}\n\n"
                f"**Command:** {' '.join(cmd)}\n\n"
                f"**stdout:** {cal_result.stdout}\n"
                f"**stderr:** {cal_result.stderr}\n"
                f"**returncode:** {cal_result.returncode}\n"
            ))
            actions.append({"action": "confirm_hold", "title": confirmed_title})
            config.notify(f"✅ Confirmed: {confirmed_title}")

        elif action == "delete":
            cmd = [cal_tool, "--delete", title]
            print(f"    Deleting: {title}")
            cal_result = subprocess.run(cmd, capture_output=True, text=True)
            _log(f"{person}_delete_{title.replace(' ', '_')[:20]}", (
                f"# Calendar Delete: {title}\n\n"
                f"**Command:** {' '.join(cmd)}\n\n"
                f"**stdout:** {cal_result.stdout}\n"
                f"**stderr:** {cal_result.stderr}\n"
                f"**returncode:** {cal_result.returncode}\n"
            ))
            actions.append({"action": "delete", "title": title})

    if not actions:
        print(f"    No events to create for {person}")
    return actions


def _expire_holds():
    """Delete [HOLD] events that are past their expiry window."""
    now = datetime.now(timezone.utc)
    events = _fetch_events(now, now + timedelta(days=30))
    holds = [e for e in events if e.get("summary", "").startswith(HOLD_PREFIX)]

    if not holds:
        return

    cal_tool = _find_calendar_tool()
    expired = []

    for hold in holds:
        summary = hold.get("summary", "")
        created_str = hold.get("created", "")
        start_str = hold["start"].get("dateTime", hold["start"].get("date", ""))

        age_expired = False
        if created_str:
            created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            if (now - created_dt) > timedelta(days=HOLD_EXPIRY_DAYS):
                age_expired = True

        proximity_expired = False
        if start_str:
            if "T" in start_str:
                start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            else:
                start_dt = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if (start_dt - now) < timedelta(hours=HOLD_EXPIRY_HOURS_BEFORE_START):
                proximity_expired = True

        if age_expired or proximity_expired:
            reason = "too old" if age_expired else "starting soon"
            cmd = [cal_tool, "--delete", summary]
            print(f"    Expiring hold ({reason}): {summary}")
            subprocess.run(cmd, capture_output=True, text=True)
            clean_title = summary.replace(HOLD_PREFIX, "", 1)
            config.notify(f"⌛ Hold expired: {clean_title} — no confirmation received")
            expired.append(summary)

    if expired:
        _log("holds_expired", (
            f"# Holds Expired\n\n"
            + "\n".join(f"- {h}" for h in expired) + "\n"
        ))


def process_schedule_flags(flags):
    """Process scheduling flags from the routing LLM response."""
    seen = set()
    unique_flags = []
    for flag in flags:
        person = flag.get("person", "")
        if person and person not in seen:
            seen.add(person)
            unique_flags.append(flag)

    _log("flags_received", (
        f"# Schedule Flags Received\n\n"
        f"**Raw flags:** {len(flags)}\n"
        f"**Unique persons:** {len(unique_flags)}\n\n"
        + "\n".join(f"- **{f.get('person')}**: {f.get('context')}" for f in unique_flags)
        + "\n"
    ))

    print(f"\n=== Auto-Calendar: {len(unique_flags)} scheduling conversation(s) flagged ===")
    all_actions = []
    for flag in unique_flags:
        person = flag["person"]
        context = flag.get("context", "")
        print(f"  {person}: {context}")
        actions = validate_and_create(person, flag_context=context)
        all_actions.extend(actions)

    print(f"\n  Checking for expired holds...")
    _expire_holds()

    if all_actions:
        print(f"\n  Total: {len(all_actions)} calendar action(s)")
    else:
        print(f"\n  No calendar events created")

    return all_actions
