"""Tests for AI pre-review and commit message suggestion."""
import json
import pytest
from unittest.mock import patch, MagicMock
import server
from server import state


@pytest.fixture(autouse=True)
def reset():
    state.reset()
    yield
    state.reset()


def _make_response(text: str):
    mock_content = MagicMock()
    mock_content.text = text
    mock_resp = MagicMock()
    mock_resp.content = [mock_content]
    return mock_resp


def _make_client(text: str):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_response(text)
    return mock_client


# ---------------------------------------------------------------------------
# _run_ai_pre_review
# ---------------------------------------------------------------------------

def test_ai_pre_review_injects_valid_comments():
    comment = json.dumps({"file": "foo.py", "line": 5, "comment": "missing null check"})
    with patch("server._HAS_ANTHROPIC", True), \
         patch("server.os.environ.get", return_value="fake-key"), \
         patch("server._anthropic.Anthropic", return_value=_make_client(comment)):
        server._run_ai_pre_review("diff text")

    comments = state.snapshot()["comments"]
    assert len(comments) == 1
    assert comments[0]["source"] == "ai"
    assert comments[0]["file"] == "foo.py"
    assert comments[0]["line"] == 5


def test_ai_pre_review_skips_malformed_lines():
    output = "not json\n" + json.dumps({"file": "a.py", "line": 1, "comment": "ok"})
    with patch("server._HAS_ANTHROPIC", True), \
         patch("server.os.environ.get", return_value="fake-key"), \
         patch("server._anthropic.Anthropic", return_value=_make_client(output)):
        server._run_ai_pre_review("diff text")

    assert len(state.snapshot()["comments"]) == 1


def test_ai_pre_review_skips_entries_missing_comment():
    output = json.dumps({"file": "a.py", "line": 1})
    with patch("server._HAS_ANTHROPIC", True), \
         patch("server.os.environ.get", return_value="fake-key"), \
         patch("server._anthropic.Anthropic", return_value=_make_client(output)):
        server._run_ai_pre_review("diff text")

    assert state.snapshot()["comments"] == []


def test_ai_pre_review_no_op_when_anthropic_missing():
    with patch("server._HAS_ANTHROPIC", False):
        server._run_ai_pre_review("diff text")

    assert state.snapshot()["comments"] == []


def test_ai_pre_review_no_op_when_api_key_missing():
    with patch("server._HAS_ANTHROPIC", True), \
         patch("server.os.environ.get", return_value=None):
        server._run_ai_pre_review("diff text")

    assert state.snapshot()["comments"] == []


def test_ai_pre_review_no_op_on_api_exception():
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("network error")
    with patch("server._HAS_ANTHROPIC", True), \
         patch("server.os.environ.get", return_value="fake-key"), \
         patch("server._anthropic.Anthropic", return_value=mock_client):
        server._run_ai_pre_review("diff text")

    assert state.snapshot()["comments"] == []


# ---------------------------------------------------------------------------
# _suggest_commit_message
# ---------------------------------------------------------------------------

def test_suggest_commit_message_returns_string():
    with patch("server._HAS_ANTHROPIC", True), \
         patch("server.os.environ.get", return_value="fake-key"), \
         patch("server._anthropic.Anthropic", return_value=_make_client("feat: add null check")):
        result = server._suggest_commit_message("diff text")

    assert result == "feat: add null check"


def test_suggest_commit_message_returns_none_when_anthropic_missing():
    with patch("server._HAS_ANTHROPIC", False):
        assert server._suggest_commit_message("diff text") is None


def test_suggest_commit_message_returns_none_when_api_key_missing():
    with patch("server._HAS_ANTHROPIC", True), \
         patch("server.os.environ.get", return_value=None):
        assert server._suggest_commit_message("diff text") is None


def test_suggest_commit_message_returns_none_on_empty_response():
    with patch("server._HAS_ANTHROPIC", True), \
         patch("server.os.environ.get", return_value="fake-key"), \
         patch("server._anthropic.Anthropic", return_value=_make_client("")):
        assert server._suggest_commit_message("diff text") is None


def test_suggest_commit_message_returns_none_on_exception():
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("timeout")
    with patch("server._HAS_ANTHROPIC", True), \
         patch("server.os.environ.get", return_value="fake-key"), \
         patch("server._anthropic.Anthropic", return_value=mock_client):
        assert server._suggest_commit_message("diff text") is None
