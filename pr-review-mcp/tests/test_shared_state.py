"""Tests for SharedState — the in-memory review session store."""
import pytest
from janus_mcp.state import SharedState


@pytest.fixture()
def s():
    st = SharedState()
    st.reset()
    return st


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------

def test_reset_clears_comments(s):
    s.add_comment("a.py", 1, "issue")
    s.reset()
    assert s.snapshot()["comments"] == []


def test_reset_clears_status(s):
    s.set_status("approved")
    s.reset()
    assert s.snapshot()["status"] == "pending"


def test_reset_clears_approved_files(s):
    s.diff_data = {"files": [{"filename": "a.py"}]}
    s.add_comment  # ensure no unresolved
    s.approved_files.add("a.py")
    s.reset()
    assert s.snapshot()["approved_files"] == []


# ---------------------------------------------------------------------------
# add_comment
# ---------------------------------------------------------------------------

def test_add_comment_returns_dict(s):
    result = s.add_comment("foo.py", 10, "needs a docstring")
    assert isinstance(result, dict)
    assert result["file"] == "foo.py"
    assert result["line"] == 10
    assert result["comment"] == "needs a docstring"
    assert result["resolved"] is False
    assert "id" in result


def test_add_comment_default_source_is_human(s):
    result = s.add_comment("foo.py", 1, "text")
    assert result["source"] == "human"


def test_add_comment_ai_source(s):
    result = s.add_comment("foo.py", 1, "text", source="ai")
    assert result["source"] == "ai"


def test_add_comment_default_side_is_left(s):
    result = s.add_comment("foo.py", 1, "text")
    assert result["side"] == "left"


def test_add_comment_invalid_parent_returns_error(s):
    result = s.add_comment("foo.py", 1, "reply", parent_id="nonexistent-id")
    assert isinstance(result, str)
    assert "not found" in result


def test_add_comment_valid_parent(s):
    parent = s.add_comment("foo.py", 1, "parent")
    child = s.add_comment("foo.py", 2, "reply", parent_id=parent["id"])
    assert isinstance(child, dict)
    assert child["parent_id"] == parent["id"]


def test_add_comment_persists(s):
    s.add_comment("foo.py", 1, "one")
    s.add_comment("foo.py", 2, "two")
    assert len(s.snapshot()["comments"]) == 2


# ---------------------------------------------------------------------------
# resolve_comment
# ---------------------------------------------------------------------------

def test_resolve_comment_marks_resolved(s):
    c = s.add_comment("foo.py", 1, "issue")
    result = s.resolve_comment(c["id"])
    assert result["resolved"] is True


def test_resolve_comment_cascades_to_replies(s):
    parent = s.add_comment("foo.py", 1, "parent")
    s.add_comment("foo.py", 2, "child", parent_id=parent["id"])
    s.resolve_comment(parent["id"])
    assert all(c["resolved"] for c in s.snapshot()["comments"])


def test_resolve_nonexistent_comment_returns_none(s):
    assert s.resolve_comment("does-not-exist") is None


# ---------------------------------------------------------------------------
# update_comment
# ---------------------------------------------------------------------------

def test_update_comment_changes_text(s):
    c = s.add_comment("foo.py", 1, "original")
    result = s.update_comment(c["id"], "updated text")
    assert result["comment"] == "updated text"


def test_update_nonexistent_comment_returns_none(s):
    assert s.update_comment("ghost", "text") is None


def test_update_comment_after_approved_returns_error(s):
    c = s.add_comment("foo.py", 1, "issue")
    s.set_status("approved")
    result = s.update_comment(c["id"], "edit")
    assert isinstance(result, str)


def test_update_comment_after_changes_requested_returns_error(s):
    c = s.add_comment("foo.py", 1, "issue")
    s.set_status("changes_requested")
    result = s.update_comment(c["id"], "edit")
    assert isinstance(result, str)


def test_update_resolved_comment_returns_error(s):
    c = s.add_comment("foo.py", 1, "issue")
    s.resolve_comment(c["id"])
    result = s.update_comment(c["id"], "edit")
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# delete_comment
# ---------------------------------------------------------------------------

def test_delete_comment_removes_it(s):
    c = s.add_comment("foo.py", 1, "to delete")
    result = s.delete_comment(c["id"])
    assert result["id"] == c["id"]
    assert s.snapshot()["comments"] == []


def test_delete_nonexistent_comment_returns_none(s):
    assert s.delete_comment("ghost") is None


def test_delete_comment_after_approved_returns_error(s):
    c = s.add_comment("foo.py", 1, "issue")
    s.set_status("approved")
    result = s.delete_comment(c["id"])
    assert isinstance(result, str)


def test_delete_resolved_comment_returns_error(s):
    c = s.add_comment("foo.py", 1, "issue")
    s.resolve_comment(c["id"])
    result = s.delete_comment(c["id"])
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# approve_file
# ---------------------------------------------------------------------------

def test_approve_file_succeeds_with_no_comments(s):
    s.diff_data = {"files": [{"filename": "a.py"}]}
    result = s.approve_file("a.py")
    assert isinstance(result, dict)
    assert "a.py" in result["approved_files"]


def test_approve_file_sets_approved_when_all_files_done(s):
    s.diff_data = {"files": [{"filename": "a.py"}]}
    result = s.approve_file("a.py")
    assert result["status"] == "approved"


def test_approve_file_stays_pending_when_others_remain(s):
    s.diff_data = {"files": [{"filename": "a.py"}, {"filename": "b.py"}]}
    result = s.approve_file("a.py")
    assert result["status"] == "pending"


def test_approve_file_with_unresolved_comment_returns_error(s):
    s.add_comment("a.py", 1, "issue")
    result = s.approve_file("a.py")
    assert isinstance(result, str)
    assert "unresolved" in result


def test_approve_file_succeeds_after_resolving_comments(s):
    s.diff_data = {"files": [{"filename": "a.py"}]}
    c = s.add_comment("a.py", 1, "issue")
    s.resolve_comment(c["id"])
    result = s.approve_file("a.py")
    assert isinstance(result, dict)
    assert result["status"] == "approved"


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------

def test_snapshot_returns_all_fields(s):
    snap = s.snapshot()
    assert "status" in snap
    assert "comments" in snap
    assert "approved_files" in snap


def test_snapshot_approved_files_is_sorted(s):
    s.diff_data = {"files": [{"filename": "z.py"}, {"filename": "a.py"}]}
    s.approve_file("z.py")
    s.approve_file("a.py")
    snap = s.snapshot()
    assert snap["approved_files"] == ["a.py", "z.py"]
