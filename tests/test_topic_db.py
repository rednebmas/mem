"""Tests for pipeline/topic_db.py."""

from conftest import seed_topics, add_activity

from pipeline.topic_db import (
    DECAY_THRESHOLD,
    compute_decay_scores,
    format_topic_tree,
    format_topic_tree_for_output,
    format_topic_tree_for_routing,
    get_topic_id,
    get_topic_summary,
    get_topic_tree,
    insert_topic,
    move_topic,
    record_activity,
    rename_topic,
    set_display_name,
    update_topic_summary,
)


# ---------------------------------------------------------------------------
# format_topic_tree
# ---------------------------------------------------------------------------

class TestFormatTopicTree:
    def test_empty(self):
        assert format_topic_tree([]) == "(no topics yet)"

    def test_flat_topics(self):
        seed_topics([("work", None, "Job stuff"), ("health", None, None)])
        topics = get_topic_tree()
        text = format_topic_tree(topics)
        assert "- work: Job stuff" in text
        assert "- health" in text
        # health has no summary, so no colon
        assert "health:" not in text

    def test_nested_topics(self):
        seed_topics([
            ("social", None, "Social life"),
            ("people", "social", None),
            ("alice", "people", "Friend"),
        ])
        topics = get_topic_tree()
        text = format_topic_tree(topics)
        lines = text.split("\n")
        assert lines[0] == "- social: Social life"
        assert lines[1] == "\t- people"
        assert lines[2] == "\t\t- alice: Friend"


# ---------------------------------------------------------------------------
# format_topic_tree_for_output (the sibling bug regression)
# ---------------------------------------------------------------------------

class TestFormatTopicTreeForOutput:
    def test_all_active_siblings_included(self):
        """Regression: early-return bug caused only the first active sibling to appear."""
        seed_topics([
            ("root", None, "Root"),
            ("alpha", "root", "First child"),
            ("beta", "root", "Second child"),
            ("gamma", "root", "Third child"),
        ])
        topics = get_topic_tree()
        # All children score above threshold
        scores = {t["id"]: 1.0 for t in topics}
        text = format_topic_tree_for_output(topics, scores)
        assert "alpha" in text
        assert "beta" in text
        assert "gamma" in text

    def test_inactive_children_excluded(self):
        seed_topics([
            ("root", None, "Root"),
            ("active", "root", "Active child"),
            ("stale", "root", "Stale child"),
        ])
        topics = get_topic_tree()
        id_map = {t["name"]: t["id"] for t in topics}
        scores = {
            id_map["root"]: 1.0,
            id_map["active"]: 1.0,
            id_map["stale"]: 0.0,
        }
        text = format_topic_tree_for_output(topics, scores)
        assert "active" in text
        assert "stale" not in text

    def test_parent_included_if_descendant_active(self):
        """A parent below threshold should still appear if it has an active child."""
        seed_topics([
            ("root", None, "Root"),
            ("mid", "root", "Mid-level"),
            ("leaf", "mid", "Active leaf"),
        ])
        topics = get_topic_tree()
        id_map = {t["name"]: t["id"] for t in topics}
        scores = {
            id_map["root"]: 1.0,
            id_map["mid"]: 0.0,   # below threshold
            id_map["leaf"]: 1.0,  # active
        }
        text = format_topic_tree_for_output(topics, scores)
        assert "mid" in text
        assert "leaf" in text

    def test_root_topics_always_included(self):
        seed_topics([("work", None, "Job"), ("health", None, None)])
        topics = get_topic_tree()
        # Even with zero scores, root topics appear
        scores = {t["id"]: 0.0 for t in topics}
        text = format_topic_tree_for_output(topics, scores)
        assert "work" in text
        assert "health" in text

    def test_empty(self):
        assert format_topic_tree_for_output([], {}) == "(no topics yet)"


# ---------------------------------------------------------------------------
# format_topic_tree_for_routing
# ---------------------------------------------------------------------------

class TestFormatTopicTreeForRouting:
    def test_active_shows_summary(self):
        seed_topics([("work", None, "Job stuff")])
        topics = get_topic_tree()
        scores = {topics[0]["id"]: 1.0}
        text = format_topic_tree_for_routing(topics, scores)
        assert "work: Job stuff" in text

    def test_inactive_shows_bare_name(self):
        seed_topics([("work", None, "Job stuff")])
        topics = get_topic_tree()
        scores = {topics[0]["id"]: 0.0}
        text = format_topic_tree_for_routing(topics, scores)
        assert "- work" in text
        assert "Job stuff" not in text

    def test_all_topics_shown(self):
        """Routing prompt shows ALL topics regardless of score."""
        seed_topics([
            ("root", None, "Root"),
            ("active", "root", "Active"),
            ("stale", "root", "Stale"),
        ])
        topics = get_topic_tree()
        id_map = {t["name"]: t["id"] for t in topics}
        scores = {id_map["root"]: 1.0, id_map["active"]: 1.0, id_map["stale"]: 0.0}
        text = format_topic_tree_for_routing(topics, scores)
        assert "active: Active" in text
        assert "stale" in text  # shown but without summary


# ---------------------------------------------------------------------------
# compute_decay_scores
# ---------------------------------------------------------------------------

class TestComputeDecayScores:
    def test_recent_activity_scores_higher(self):
        seed_topics([("a", None, None), ("b", None, None)])
        add_activity("a", days_ago=1)
        add_activity("b", days_ago=30)
        scores = compute_decay_scores()
        id_a = get_topic_id("a")
        id_b = get_topic_id("b")
        assert scores[id_a] > scores[id_b]

    def test_no_activity_scores_zero(self):
        seed_topics([("empty", None, None)])
        scores = compute_decay_scores()
        tid = get_topic_id("empty")
        assert scores[tid] == 0.0

    def test_parent_accumulates_child_scores(self):
        seed_topics([("parent", None, None), ("child", "parent", None)])
        add_activity("child", days_ago=1)
        scores = compute_decay_scores()
        parent_id = get_topic_id("parent")
        child_id = get_topic_id("child")
        # Parent has no own activity, but inherits child's score
        assert scores[parent_id] == scores[child_id]
        assert scores[parent_id] > 0

    def test_multiple_activities_accumulate(self):
        seed_topics([("busy", None, None)])
        add_activity("busy", days_ago=1)
        add_activity("busy", days_ago=2)
        add_activity("busy", days_ago=3)
        scores = compute_decay_scores()
        tid = get_topic_id("busy")
        # Should be sum of three decay values
        assert scores[tid] > 0.5 ** (1 / 14.0)  # more than a single 1-day-old activity


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------

class TestTopicCrud:
    def test_insert_and_get(self):
        tid = insert_topic("new-topic", summary="A topic")
        assert tid is not None
        assert get_topic_id("new-topic") == tid
        assert get_topic_summary("new-topic") == "A topic"

    def test_insert_duplicate_returns_existing_id(self):
        id1 = insert_topic("dup")
        id2 = insert_topic("dup")
        assert id1 == id2

    def test_insert_with_parent(self):
        insert_topic("parent")
        insert_topic("child", parent_name="parent")
        topics = get_topic_tree()
        child = [t for t in topics if t["name"] == "child"][0]
        assert child["parent_name"] == "parent"

    def test_rename(self):
        insert_topic("old-name")
        rename_topic("old-name", "new-name")
        assert get_topic_id("old-name") is None
        assert get_topic_id("new-name") is not None

    def test_rename_noop_if_target_exists(self):
        insert_topic("a")
        insert_topic("b")
        rename_topic("a", "b")
        # Both should still exist
        assert get_topic_id("a") is not None
        assert get_topic_id("b") is not None

    def test_move_topic(self):
        insert_topic("parent")
        insert_topic("child")
        move_topic("child", "parent")
        topics = get_topic_tree()
        child = [t for t in topics if t["name"] == "child"][0]
        assert child["parent_name"] == "parent"

    def test_move_to_root(self):
        insert_topic("parent")
        insert_topic("child", parent_name="parent")
        move_topic("child", None)
        topics = get_topic_tree()
        child = [t for t in topics if t["name"] == "child"][0]
        assert child["parent_id"] is None

    def test_update_summary(self):
        insert_topic("t", summary="old")
        update_topic_summary("t", "new")
        assert get_topic_summary("t") == "new"

    def test_record_activity(self):
        insert_topic("t")
        record_activity("t", "browser", "visited example.com")
        scores = compute_decay_scores()
        assert scores[get_topic_id("t")] > 0

    def test_record_activity_creates_topic(self):
        """record_activity should auto-create the topic if it doesn't exist."""
        record_activity("auto-created", "test", "some context")
        assert get_topic_id("auto-created") is not None


# ---------------------------------------------------------------------------
# display_name
# ---------------------------------------------------------------------------

class TestDisplayName:
    def test_insert_with_display_name(self):
        insert_topic("ai-tools", display_name="AI Tools")
        topics = get_topic_tree()
        t = [t for t in topics if t["name"] == "ai-tools"][0]
        assert t["display_name"] == "AI Tools"

    def test_insert_without_display_name(self):
        insert_topic("plain")
        topics = get_topic_tree()
        t = [t for t in topics if t["name"] == "plain"][0]
        assert t["display_name"] is None

    def test_set_display_name(self):
        insert_topic("my-topic")
        set_display_name("my-topic", "My Topic")
        topics = get_topic_tree()
        t = [t for t in topics if t["name"] == "my-topic"][0]
        assert t["display_name"] == "My Topic"

    def test_output_uses_display_name(self):
        """format_topic_tree_for_output should use display_name when available."""
        seed_topics([("ai-and-coding", None, "AI stuff")])
        set_display_name("ai-and-coding", "AI and Coding")
        topics = get_topic_tree()
        scores = {t["id"]: 1.0 for t in topics}
        text = format_topic_tree_for_output(topics, scores)
        assert "AI and Coding: AI stuff" in text
        assert "ai-and-coding" not in text

    def test_output_falls_back_to_name(self):
        """format_topic_tree_for_output falls back to name when no display_name."""
        seed_topics([("work", None, "Job")])
        topics = get_topic_tree()
        scores = {t["id"]: 1.0 for t in topics}
        text = format_topic_tree_for_output(topics, scores)
        assert "work: Job" in text

    def test_routing_tree_uses_slug(self):
        """format_topic_tree_for_routing should always use slug name, not display_name."""
        seed_topics([("ai-and-coding", None, "AI stuff")])
        set_display_name("ai-and-coding", "AI and Coding")
        topics = get_topic_tree()
        scores = {t["id"]: 1.0 for t in topics}
        text = format_topic_tree_for_routing(topics, scores)
        assert "ai-and-coding: AI stuff" in text
        assert "AI and Coding" not in text
