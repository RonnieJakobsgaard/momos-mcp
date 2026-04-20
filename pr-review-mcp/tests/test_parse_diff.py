"""Tests for parse_diff — the unified-diff parser."""
import pytest
from janus_mcp.server import parse_diff


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_diff(filename: str, old_lines: list[str], new_lines: list[str],
               old_start: int = 1, new_start: int = 1) -> str:
    removed = [f"-{l}" for l in old_lines]
    added = [f"+{l}" for l in new_lines]
    old_count = len(old_lines)
    new_count = len(new_lines)
    hunk_header = f"@@ -{old_start},{old_count} +{new_start},{new_count} @@"
    return "\n".join([
        f"diff --git a/{filename} b/{filename}",
        f"index abc1234..def5678 100644",
        f"--- a/{filename}",
        f"+++ b/{filename}",
        hunk_header,
        *removed,
        *added,
    ]) + "\n"


# ---------------------------------------------------------------------------
# basic structure
# ---------------------------------------------------------------------------

def test_empty_diff_returns_no_files():
    result = parse_diff("")
    assert result["files"] == []


def test_single_file_parsed():
    raw = _make_diff("foo.py", ["old line\n"], ["new line\n"])
    result = parse_diff(raw)
    assert len(result["files"]) == 1
    assert result["files"][0]["filename"] == "foo.py"


def test_multiple_files_parsed():
    raw = _make_diff("a.py", ["x\n"], ["y\n"]) + _make_diff("b.py", ["p\n"], ["q\n"])
    result = parse_diff(raw)
    assert len(result["files"]) == 2
    assert {f["filename"] for f in result["files"]} == {"a.py", "b.py"}


def test_filename_strips_b_prefix():
    raw = (
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-old\n"
        "+new\n"
    )
    result = parse_diff(raw)
    assert result["files"][0]["filename"] == "src/main.py"


# ---------------------------------------------------------------------------
# line types
# ---------------------------------------------------------------------------

def test_added_lines_have_correct_type():
    raw = (
        "diff --git a/f.py b/f.py\n"
        "--- a/f.py\n"
        "+++ b/f.py\n"
        "@@ -1,0 +1,2 @@\n"
        "+line one\n"
        "+line two\n"
    )
    result = parse_diff(raw)
    lines = result["files"][0]["hunks"][0]["lines"]
    assert all(l["type"] == "add" for l in lines)


def test_removed_lines_have_correct_type():
    raw = (
        "diff --git a/f.py b/f.py\n"
        "--- a/f.py\n"
        "+++ b/f.py\n"
        "@@ -1,2 +1,0 @@\n"
        "-line one\n"
        "-line two\n"
    )
    result = parse_diff(raw)
    lines = result["files"][0]["hunks"][0]["lines"]
    assert all(l["type"] == "remove" for l in lines)


def test_context_lines_have_correct_type():
    raw = (
        "diff --git a/f.py b/f.py\n"
        "--- a/f.py\n"
        "+++ b/f.py\n"
        "@@ -1,3 +1,3 @@\n"
        " ctx\n"
        "-old\n"
        "+new\n"
        " ctx2\n"
    )
    result = parse_diff(raw)
    lines = result["files"][0]["hunks"][0]["lines"]
    types = [l["type"] for l in lines]
    assert types == ["context", "remove", "add", "context"]


def test_no_newline_marker_is_skipped():
    raw = (
        "diff --git a/f.py b/f.py\n"
        "--- a/f.py\n"
        "+++ b/f.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-old\n"
        "\\ No newline at end of file\n"
        "+new\n"
    )
    result = parse_diff(raw)
    lines = result["files"][0]["hunks"][0]["lines"]
    types = [l["type"] for l in lines]
    assert "no_newline" not in types
    assert len(lines) == 2  # only remove + add


# ---------------------------------------------------------------------------
# line number tracking
# ---------------------------------------------------------------------------

def test_added_lines_have_new_line_numbers():
    raw = (
        "diff --git a/f.py b/f.py\n"
        "--- a/f.py\n"
        "+++ b/f.py\n"
        "@@ -1,0 +5,2 @@\n"
        "+first\n"
        "+second\n"
    )
    result = parse_diff(raw)
    lines = result["files"][0]["hunks"][0]["lines"]
    assert lines[0]["new_line"] == 5
    assert lines[1]["new_line"] == 6
    assert lines[0]["old_line"] is None


def test_removed_lines_have_old_line_numbers():
    raw = (
        "diff --git a/f.py b/f.py\n"
        "--- a/f.py\n"
        "+++ b/f.py\n"
        "@@ -3,2 +3,0 @@\n"
        "-gone one\n"
        "-gone two\n"
    )
    result = parse_diff(raw)
    lines = result["files"][0]["hunks"][0]["lines"]
    assert lines[0]["old_line"] == 3
    assert lines[1]["old_line"] == 4
    assert lines[0]["new_line"] is None


def test_context_lines_have_both_line_numbers():
    raw = (
        "diff --git a/f.py b/f.py\n"
        "--- a/f.py\n"
        "+++ b/f.py\n"
        "@@ -10,1 +10,1 @@\n"
        " context\n"
    )
    result = parse_diff(raw)
    line = result["files"][0]["hunks"][0]["lines"][0]
    assert line["old_line"] == 10
    assert line["new_line"] == 10


# ---------------------------------------------------------------------------
# multiple hunks
# ---------------------------------------------------------------------------

def test_multiple_hunks_in_one_file():
    raw = (
        "diff --git a/f.py b/f.py\n"
        "--- a/f.py\n"
        "+++ b/f.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-old1\n"
        "+new1\n"
        "@@ -10,1 +10,1 @@\n"
        "-old2\n"
        "+new2\n"
    )
    result = parse_diff(raw)
    assert len(result["files"][0]["hunks"]) == 2


def test_hunk_header_stored():
    raw = (
        "diff --git a/f.py b/f.py\n"
        "--- a/f.py\n"
        "+++ b/f.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-old\n"
        "+new\n"
    )
    result = parse_diff(raw)
    assert result["files"][0]["hunks"][0]["header"].startswith("@@")


# ---------------------------------------------------------------------------
# content stripping
# ---------------------------------------------------------------------------

def test_line_content_strips_diff_prefix():
    raw = (
        "diff --git a/f.py b/f.py\n"
        "--- a/f.py\n"
        "+++ b/f.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-old content\n"
        "+new content\n"
    )
    result = parse_diff(raw)
    lines = result["files"][0]["hunks"][0]["lines"]
    assert lines[0]["content"] == "old content"
    assert lines[1]["content"] == "new content"
