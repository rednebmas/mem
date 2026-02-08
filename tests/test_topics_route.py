"""Tests for pipeline/topics_route.py — JSON parsing and prompt generation (no LLM calls)."""

import json
import pytest

from conftest import seed_topics
from pipeline.topic_db import set_display_name
from pipeline.topics_route import _parse_json, generate_routing_prompt


class TestParseJson:
    def test_plain_json(self):
        result = _parse_json('{"existing_topics": {}, "new_topics": []}')
        assert result == {"existing_topics": {}, "new_topics": []}

    def test_json_fenced(self):
        text = '```json\n{"key": "value"}\n```'
        assert _parse_json(text) == {"key": "value"}

    def test_json_fenced_with_preamble(self):
        text = 'Here is the result:\n```json\n{"key": "value"}\n```\nDone.'
        assert _parse_json(text) == {"key": "value"}

    def test_generic_fence(self):
        text = '```\n{"key": "value"}\n```'
        assert _parse_json(text) == {"key": "value"}

    def test_multiple_fences_takes_json_one(self):
        text = '```\nsome text\n```\n```json\n{"key": "value"}\n```'
        assert _parse_json(text) == {"key": "value"}

    def test_whitespace_around_json(self):
        text = '  \n  {"key": "value"}  \n  '
        assert _parse_json(text) == {"key": "value"}

    def test_invalid_json_raises(self):
        with pytest.raises((json.JSONDecodeError, ValueError)):
            _parse_json("not json at all")

    def test_full_routing_response(self):
        """Realistic LLM response with all fields."""
        response = '''```json
{
  "existing_topics": {
    "ai-and-coding": {
      "note": "Browsed Claude pricing",
      "updated_summary": "AI development and tools."
    }
  },
  "new_topics": [
    {"name": "new-tool", "parent": "ai-and-coding", "summary": "A new AI tool"}
  ],
  "renames": {"old-name": "new-name"},
  "moves": {"child": "new-parent"},
  "scheduling": []
}
```'''
        result = _parse_json(response)
        assert "ai-and-coding" in result["existing_topics"]
        assert len(result["new_topics"]) == 1
        assert result["renames"]["old-name"] == "new-name"
        assert result["moves"]["child"] == "new-parent"

    def test_nested_fences(self):
        """JSON fence inside other content."""
        text = 'Analysis:\n\n```json\n{"a": 1}\n```\n\nExplanation of results.'
        assert _parse_json(text) == {"a": 1}

    def test_empty_routing_response(self):
        response = '{"existing_topics": {}, "new_topics": [], "renames": {}, "moves": {}, "scheduling": []}'
        result = _parse_json(response)
        assert result["existing_topics"] == {}
        assert result["new_topics"] == []


# ---------------------------------------------------------------------------
# generate_routing_prompt
# ---------------------------------------------------------------------------

class TestGenerateRoutingPrompt:
    def test_replaces_parent_example(self):
        seed_topics([
            ("business", None, "Acme Corp"),
            ("project-a", "business", "First project"),
            ("project-b", "business", "Second project"),
        ])
        path = generate_routing_prompt()
        text = path.read_text()
        assert '"business" → "Acme Corp."' in text
        assert "Stark Industries" not in text

    def test_replaces_person_example(self):
        seed_topics([
            ("social", None, "Social life"),
            ("people", "social", None),
            ("alice", "people", "Friend"),
        ])
        path = generate_routing_prompt()
        text = path.read_text()
        assert '"people/alice"' in text
        assert "pepper-potts" not in text

    def test_bad_example_mentions_real_children(self):
        seed_topics([
            ("business", None, "Acme Corp"),
            ("alpha", "business", "First"),
            ("beta", "business", "Second"),
        ])
        set_display_name("alpha", "Alpha")
        set_display_name("beta", "Beta")
        path = generate_routing_prompt()
        text = path.read_text()
        assert "Includes Alpha and Beta" in text

    def test_no_topics_uses_defaults(self):
        """With no topics at all, the original examples stay."""
        path = generate_routing_prompt()
        text = path.read_text()
        assert "Stark Industries" in text
        assert "pepper-potts" in text
