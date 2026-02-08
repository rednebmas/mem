"""Per-topic contextualization via LLM."""

from datetime import datetime

from . import config
from .ollama_client import generate
from .topic_db import get_topic_summary, update_topic_summary

CONTEXT_CTX = 8192

CONTEXT_PROMPT = """You are maintaining a personal knowledge profile for {user}'s AI assistant. The goal is to deeply understand {user} so the assistant can give highly personalized, relevant responses.

You are updating the summary for the topic: "{{topic_name}}"

Here is the current summary for this topic:
---
{{existing_summary}}
---

Here are new notes about this topic from recent activity:
---
{{new_notes}}
---

Write an updated summary incorporating the new information. Rules:
- Max 200 words. Be concise — bullet points of specific facts only.
- Write ONLY facts specific to what happened. No generic descriptions, no "Next Steps", no "Implications".
- If the activity is just "used MyChart", say that. Don't extrapolate into healthcare strategy.
- Preserve important existing context that's still relevant
- Drop stale details that have been superseded
- If nothing meaningful changed, output "NO_UPDATE"

GOOD: "- Researched backcountry ski routes near Mt. Baker on TAY"
BAD: "- Demonstrates a growing interest in outdoor winter recreation and alpine exploration"

Output ONLY the updated summary text, no preamble."""


def contextualize_topic(topic_name, notes):
    """Update a single topic's summary given new notes."""
    existing = get_topic_summary(topic_name)
    existing_text = existing if existing else "No existing summary — this is a new topic."

    rendered_prompt = config.render_template(CONTEXT_PROMPT)
    prompt = rendered_prompt.format(
        topic_name=topic_name,
        existing_summary=existing_text,
        new_notes="\n".join(f"- {n}" for n in notes),
    )
    raw = generate(prompt, context_length=CONTEXT_CTX)
    debug_dir = config.get_debug_dir()
    ts = datetime.now().strftime("%H%M%S")
    (debug_dir / f"{ts}_ctx_{topic_name}.md").write_text(
        f"# Prompt\n\n{prompt}\n\n# Response\n\n{raw}\n"
    )
    result = raw.strip()

    if result == "NO_UPDATE":
        return False
    update_topic_summary(topic_name, result)
    return True


def contextualize_all(notes_by_topic):
    """Run contextualization for all topics with new notes.

    Args:
        notes_by_topic: {topic_name: [list of notes]} from route_all()

    Returns:
        Number of topics updated.
    """
    updated = 0
    for topic_name, notes in notes_by_topic.items():
        if not notes:
            continue
        print(f"Contextualizing {topic_name}...")
        if contextualize_topic(topic_name, notes):
            updated += 1
            print(f"  Updated summary")
        else:
            print(f"  No update needed")
    return updated
