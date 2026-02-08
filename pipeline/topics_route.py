"""Topic routing + contextualization via LLM (single call with all sources)."""

import json
import sys
from datetime import datetime

from . import config
from .ollama_client import generate
from .topic_db import (
    DECAY_THRESHOLD,
    compute_decay_scores,
    format_topic_tree,
    format_topic_tree_for_routing,
    get_latest_activity_dates,
    get_topic_tree,
    insert_topic,
    move_topic,
    record_activity,
    rename_topic,
    update_topic_summary,
)


ROUTING_PROMPT = """You are maintaining a personal knowledge profile for {user}'s AI assistant. The goal is to deeply understand {user} — their interests, projects, relationships, habits, and life context — so the assistant can give highly personalized, relevant responses instead of generic ones.

About {user}: {user_bio}

Here are the current topics being tracked (with their current summaries).
Topics shown without a summary (just the name) are inactive/dormant — they exist but have had no recent activity. You can route activity to them. Do NOT create duplicates of these.
---
{{topic_tree}}
---

Here is recent activity from all sources:
---
{{all_sources}}
---

For each piece of activity, either:
1. Map it to an EXISTING topic using its EXACT name as written above
2. Suggest a new topic (with a parent if it's a subtopic)
3. Skip it if it's routine/noise

For each topic that has new activity, provide:
- "note": what specifically happened (this gets logged as activity)
- "updated_summary": a timeless 1-2 sentence description of what this topic IS — no dates, no "as of", no "currently". The system tracks recency via activity timestamps and decay scoring. Temporary or situational info (e.g., recovering from injury, shopping for X, planning a trip) should be its own subtopic so it naturally ages out.
  CRITICAL: Named entities (apps, tools, services, companies) must be their own subtopics. Parent summaries describe ONLY the category itself — never mention specific children by name. If you can name it, it's a subtopic.
  GOOD parent: "business" → "Consulting LLC."  (children carry the details)
  BAD parent: "business" → "Consulting LLC. Active projects include ProjectX and ProjectY."  (naming children in parent)

TOPIC NAMES: Use existing topic names when the activity fits. If a topic belongs under a different parent (or should become a root topic), use the "moves" field.

RENAMES: Rename when a topic's name no longer fits, or when reorganizing the tree (e.g., renaming a broad topic before splitting its subtopics into separate branches).

TOPIC STRUCTURE:
- NEVER create new top-level topics. The existing root categories cover the user's life. Every new topic must be a subtopic under an existing parent. If something doesn't fit, pick the closest parent.
- Subtopics must be genuine subcategories of the parent — not just loosely related. "kiteboarding" is a subcategory of "outdoor recreation". "entertainment" is NOT a subcategory of "music".
- The "people" subtopic under "social" tracks relationships. Create person subtopics under "people" for individuals the user interacts with meaningfully. The summary should describe the relationship, not log individual conversations.
- Topics can be reorganized as they evolve. If a subtopic grows complex enough to warrant its own children, that's fine — the tree can be multiple levels deep.

SKIP routine noise that doesn't reveal anything personal: delivery notifications, 2FA codes, parking confirmations, spam texts, generic browsing.

{action_instructions}

Output as JSON:
{{{{"existing_topics": {{{{
    "topic name": {{{{"note": "What specifically happened", "updated_summary": "Short description of what this topic covers"}}}}
  }}}},
  "new_topics": [
    {{{{"name": "new topic name", "parent": "parent or null", "summary": "Timeless description of what this topic IS (no dates)"}}}}
  ],
  "renames": {{{{
    "old name": "new name"
  }}}},
  "moves": {{{{
    "topic name": "new parent name or null"
  }}}}{action_output_fields}
}}}}

Output ONLY valid JSON, no other text."""


def _log(label, prompt, response):
    """Write prompt/response to debug dir for inspection."""
    debug_dir = config.get_debug_dir()
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = debug_dir / f"{ts}_{label}.md"
    path.write_text(f"# Prompt\n\n{prompt}\n\n# Response\n\n{response}\n")
    print(f"  Debug log: {path}")


def _log_topic_tree():
    """Write the full topic tree to a debug file (names, summaries, and scores)."""
    debug_dir = config.get_debug_dir()
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    topics = get_topic_tree()
    short = format_topic_tree([{**t, "summary": None} for t in topics])
    full = format_topic_tree(topics)
    scores = compute_decay_scores()
    dates = get_latest_activity_dates()
    by_parent = {}
    for t in topics:
        by_parent.setdefault(t["parent_id"], []).append(t)
    score_lines = []
    def _render_scores(parent_id, indent=0):
        for t in by_parent.get(parent_id, []):
            prefix = "\t" * indent + "- "
            score = scores.get(t["id"], 0.0)
            last = dates.get(t["id"], "never")
            score_lines.append(f"{prefix}{t['name']}  (score: {score:.2f}, last: {last})")
            _render_scores(t["id"], indent + 1)
    _render_scores(None)
    scored = "\n".join(score_lines)

    path = debug_dir / f"{ts}_topic_tree.md"
    path.write_text(
        f"# Topic Tree\n\n{short}\n\n"
        f"# Topic Tree (with summaries)\n\n{full}\n\n"
        f"# Topic Tree (with scores)\n\n{scored}\n"
    )
    print(f"  Topic tree: {path}")


def _estimate_ctx(text):
    """Estimate needed context: input tokens * 2 for output headroom, min 8k."""
    tokens = len(text) // 3
    return max(8192, min(32768, tokens * 2))


def _parse_json(text):
    """Extract JSON from LLM response, handling markdown fences and extra text."""
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


def route_all(results, activity_date=None, actions=None):
    """Route all sources in a single LLM call.

    Args:
        results: dict from collect_all() — {source_name: filtered_items_string}
        activity_date: datetime for when the data occurred (passed to record_activity)
        actions: list of action dicts from actions.load_actions()

    Returns:
        Tuple of (total_updates, full_result_dict).
    """
    topics = get_topic_tree()
    if not topics:
        print("Error: no seed topics in DB. Run 'mem reseed <dir>' first.")
        return 0, {}


    from .ingest import format_output
    all_text = format_output(results)
    scores = compute_decay_scores()
    tree_text = format_topic_tree_for_routing(topics, scores)

    # Build action prompt additions
    action_instructions = ""
    action_output_fields = ""
    if actions:
        from .actions import get_action_prompt_additions, get_action_output_fields
        action_instructions = get_action_prompt_additions(actions)
        output_fields = get_action_output_fields(actions)
        if output_fields:
            # Format as JSON snippet to insert into the schema
            lines = []
            for key, example in output_fields.items():
                lines.append(f',\n  "{key}": {json.dumps(example)}')
            action_output_fields = "".join(lines)

    rendered_prompt = config.render_template(ROUTING_PROMPT)
    prompt = rendered_prompt.format(
        topic_tree=tree_text,
        all_sources=all_text,
        action_instructions=action_instructions,
        action_output_fields=action_output_fields,
    )
    ctx = _estimate_ctx(prompt)
    print("Routing all sources...")
    raw = generate(prompt, context_length=ctx)
    _log("route_all", prompt, raw)
    try:
        result = _parse_json(raw)
    except json.JSONDecodeError:
        print("  Warning: JSON parse error, retrying...")
        raw = generate(prompt, context_length=ctx)
        _log("route_all_retry", prompt, raw)
        try:
            result = _parse_json(raw)
        except json.JSONDecodeError:
            print("  Warning: JSON parse failed after retry")
            return 0, {}

    for old_name, new_name in result.get("renames", {}).items():
        rename_topic(old_name, new_name)
        print(f"  Renamed: {old_name} → {new_name}")
    for topic_name, new_parent in result.get("moves", {}).items():
        move_topic(topic_name, new_parent)
        print(f"  Moved: {topic_name} → {new_parent or 'root'}")

    updated_count = 0
    for name, data in result.get("existing_topics", {}).items():
        note = data.get("note", "") if isinstance(data, dict) else data
        summary = data.get("updated_summary", "") if isinstance(data, dict) else ""
        if isinstance(summary, list):
            summary = "\n".join(summary)
        record_activity(name, "all", note, activity_date=activity_date)
        if summary:
            update_topic_summary(name, summary)
            updated_count += 1

    for topic in result.get("new_topics", []):
        name = topic["name"]
        parent = topic.get("parent")
        summary = topic.get("summary", "")
        if isinstance(summary, list):
            summary = "\n".join(summary)
        insert_topic(name, parent_name=parent, summary=summary)
        record_activity(name, "all", summary, activity_date=activity_date)
        updated_count += 1

    _log_topic_tree()

    return updated_count, result
