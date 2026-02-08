"""Tests for pipeline/topics_route.py — JSON parsing only (no LLM calls)."""

import json
import pytest

from pipeline.topics_route import _parse_json


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
