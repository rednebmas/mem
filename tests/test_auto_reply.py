"""Tests for pipeline/auto_reply.py — draft reply generation and dedup."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

from pipeline.auto_reply import (
    _extract_person_thread,
    _format_calendar,
    process_unanswered_flags,
    draft_reply,
    _load_seen,
    _save_seen,
)


SAMPLE_TEXTS = """Craig Dobbins (5 messages):
  [Feb 6, 10:30 AM] Craig: Hey are you free this weekend?
  [Feb 6, 10:35 AM] Sam: Maybe Saturday afternoon
  [Feb 6, 10:40 AM] Craig: Cool, want to jam?
  [Feb 6, 10:45 AM] Craig: I got a new pedal
  [Feb 6, 10:50 AM] Craig: Let me know!

Jarid (3 messages):
  [Feb 7, 2:00 PM] Jarid: Can you review the pump PR?
  [Feb 7, 2:05 PM] Sam: Sure, I'll look tonight
  [Feb 7, 8:00 PM] Jarid: Any updates?
"""


class TestExtractPersonThread:
    def test_extracts_correct_person(self):
        thread = _extract_person_thread(SAMPLE_TEXTS, "Craig")
        assert thread is not None
        assert "Craig Dobbins" in thread
        assert "new pedal" in thread
        assert "Jarid" not in thread

    def test_extracts_second_person(self):
        thread = _extract_person_thread(SAMPLE_TEXTS, "Jarid")
        assert thread is not None
        assert "Jarid" in thread
        assert "pump PR" in thread

    def test_missing_person_returns_none(self):
        assert _extract_person_thread(SAMPLE_TEXTS, "Nobody") is None

    def test_empty_texts_returns_none(self):
        assert _extract_person_thread("", "Craig") is None


class TestFormatCalendar:
    def test_empty_events(self):
        assert _format_calendar([]) == "(no upcoming events)"

    def test_formats_events(self):
        events = [{
            "summary": "Dinner with Craig",
            "start": {"dateTime": "2026-02-10T18:00:00-08:00"},
            "end": {"dateTime": "2026-02-10T19:00:00-08:00"},
        }]
        result = _format_calendar(events)
        assert "Dinner with Craig" in result


class TestSeenState:
    def test_save_and_load_roundtrip(self, instance_dir):
        seen = {"Craig": datetime.now(timezone.utc).isoformat()}
        _save_seen(seen)
        loaded = _load_seen()
        assert "Craig" in loaded

    def test_expires_old_entries(self, instance_dir):
        old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        seen = {"Craig": old_time}
        _save_seen(seen)
        loaded = _load_seen()
        assert "Craig" not in loaded

    def test_keeps_recent_entries(self, instance_dir):
        recent_time = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
        seen = {"Craig": recent_time}
        _save_seen(seen)
        loaded = _load_seen()
        assert "Craig" in loaded


class TestProcessUnansweredFlags:
    @patch("pipeline.auto_reply.draft_reply", return_value="Sounds good!")
    @patch("pipeline.auto_reply._send_draft_to_telegram")
    @patch("pipeline.auto_reply._load_seen", return_value={})
    @patch("pipeline.auto_reply._save_seen")
    def test_sends_draft_for_new_person(self, mock_save, mock_load, mock_send, mock_draft):
        flags = [{"person": "Craig", "context": "asked about jamming"}]
        result = process_unanswered_flags(flags)
        assert result == 1
        mock_draft.assert_called_once_with("Craig", flag_context="asked about jamming")
        mock_send.assert_called_once_with("Craig", "Sounds good!")

    @patch("pipeline.auto_reply.draft_reply")
    @patch("pipeline.auto_reply._send_draft_to_telegram")
    @patch("pipeline.auto_reply._load_seen", return_value={
        "Craig": datetime.now(timezone.utc).isoformat()
    })
    @patch("pipeline.auto_reply._save_seen")
    def test_skips_recently_seen_person(self, mock_save, mock_load, mock_send, mock_draft):
        flags = [{"person": "Craig", "context": "asked about jamming"}]
        result = process_unanswered_flags(flags)
        assert result == 0
        mock_draft.assert_not_called()

    @patch("pipeline.auto_reply.draft_reply", return_value=None)
    @patch("pipeline.auto_reply._send_draft_to_telegram")
    @patch("pipeline.auto_reply._load_seen", return_value={})
    @patch("pipeline.auto_reply._save_seen")
    def test_no_draft_no_send(self, mock_save, mock_load, mock_send, mock_draft):
        flags = [{"person": "Craig", "context": "just a link"}]
        result = process_unanswered_flags(flags)
        assert result == 0
        mock_send.assert_not_called()

    @patch("pipeline.auto_reply.draft_reply", side_effect=["Hey!", "On it!"])
    @patch("pipeline.auto_reply._send_draft_to_telegram")
    @patch("pipeline.auto_reply._load_seen", return_value={})
    @patch("pipeline.auto_reply._save_seen")
    def test_deduplicates_same_person(self, mock_save, mock_load, mock_send, mock_draft):
        flags = [
            {"person": "Craig", "context": "msg 1"},
            {"person": "Craig", "context": "msg 2"},
            {"person": "Jarid", "context": "msg 3"},
        ]
        result = process_unanswered_flags(flags)
        assert result == 2
        assert mock_draft.call_count == 2


class TestDraftReply:
    @patch("pipeline.auto_reply._fetch_events", return_value=[])
    @patch("pipeline.auto_reply.generate", return_value="Yeah I'm down, Saturday afternoon works!")
    @patch("pipeline.auto_reply.TextsSource")
    def test_generates_draft(self, mock_texts_cls, mock_generate, mock_events, instance_dir):
        mock_source = MagicMock()
        mock_source.collect.return_value = SAMPLE_TEXTS
        mock_texts_cls.return_value = mock_source

        result = draft_reply("Craig", "asked about jamming this weekend")
        assert result is not None
        assert "Saturday" in result

    @patch("pipeline.auto_reply._fetch_events", return_value=[])
    @patch("pipeline.auto_reply.generate", return_value="SKIP")
    @patch("pipeline.auto_reply.TextsSource")
    def test_skip_response(self, mock_texts_cls, mock_generate, mock_events, instance_dir):
        mock_source = MagicMock()
        mock_source.collect.return_value = SAMPLE_TEXTS
        mock_texts_cls.return_value = mock_source

        result = draft_reply("Craig")
        assert result is None

    @patch("pipeline.auto_reply.TextsSource")
    def test_no_texts_returns_none(self, mock_texts_cls, instance_dir):
        mock_source = MagicMock()
        mock_source.collect.return_value = None
        mock_texts_cls.return_value = mock_source

        result = draft_reply("Craig")
        assert result is None

    @patch("pipeline.auto_reply.TextsSource")
    def test_no_thread_returns_none(self, mock_texts_cls, instance_dir):
        mock_source = MagicMock()
        mock_source.collect.return_value = "Some Other Person (1 messages):\n  [Feb 7] Other: hey"
        mock_texts_cls.return_value = mock_source

        result = draft_reply("Craig")
        assert result is None


class TestActionRegistration:
    def test_auto_reply_registered(self):
        from pipeline.actions import _BUILTIN_HANDLERS
        assert "auto-reply" in _BUILTIN_HANDLERS

    def test_detect_prompt_exists(self):
        from pipeline.actions import _load_builtin
        action = _load_builtin("auto-reply")
        assert action is not None
        assert "unanswered" in action["detect_prompt"].lower()
        assert "unanswered_texts" in action["output_schema"]
