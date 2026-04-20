"""Integration tests for the HTTP review server."""
import http.client
import json
import pytest
import janus_mcp.server as server
from janus_mcp.server import state


@pytest.fixture(autouse=True)
def reset():
    state.reset()
    with state.lock:
        state.diff_data = {}
    yield
    state.reset()


def _conn():
    return http.client.HTTPConnection("localhost", state.port, timeout=5)


def _get(path: str) -> tuple[int, dict]:
    conn = _conn()
    conn.request("GET", path)
    resp = conn.getresponse()
    body = json.loads(resp.read())
    return resp.status, body


def _post(path: str, data: dict) -> tuple[int, dict]:
    payload = json.dumps(data).encode()
    conn = _conn()
    conn.request("POST", path, body=payload, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    body = json.loads(resp.read())
    return resp.status, body


def _put(path: str, data: dict) -> tuple[int, dict]:
    payload = json.dumps(data).encode()
    conn = _conn()
    conn.request("PUT", path, body=payload, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    body = json.loads(resp.read())
    return resp.status, body


def _delete(path: str) -> tuple[int, dict]:
    conn = _conn()
    conn.request("DELETE", path)
    resp = conn.getresponse()
    body = json.loads(resp.read())
    return resp.status, body


# ---------------------------------------------------------------------------
# GET /comments
# ---------------------------------------------------------------------------

def test_get_comments_initial_state():
    status, body = _get("/comments")
    assert status == 200
    assert body["status"] == "pending"
    assert body["comments"] == []


def test_get_comments_after_adding():
    state.add_comment("foo.py", 1, "issue")
    status, body = _get("/comments")
    assert status == 200
    assert len(body["comments"]) == 1


# ---------------------------------------------------------------------------
# GET /diff
# ---------------------------------------------------------------------------

def test_get_diff_empty():
    status, body = _get("/diff")
    assert status == 200
    assert body == {}


def test_get_diff_returns_diff_data():
    with state.lock:
        state.diff_data = {"files": [{"filename": "a.py", "hunks": []}]}
    status, body = _get("/diff")
    assert status == 200
    assert len(body["files"]) == 1


# ---------------------------------------------------------------------------
# GET unknown path
# ---------------------------------------------------------------------------

def test_get_unknown_path_returns_404():
    status, body = _get("/nope")
    assert status == 404


# ---------------------------------------------------------------------------
# POST /comments
# ---------------------------------------------------------------------------

def test_post_comment_creates_entry():
    status, body = _post("/comments", {"file": "a.py", "line": 5, "comment": "fix this"})
    assert status == 201
    assert body["file"] == "a.py"
    assert body["line"] == 5
    assert body["comment"] == "fix this"
    assert "id" in body


def test_post_comment_missing_comment_returns_400():
    status, body = _post("/comments", {"file": "a.py", "line": 1})
    assert status == 400


def test_post_comment_invalid_parent_returns_404():
    status, body = _post("/comments", {
        "file": "a.py", "line": 1, "comment": "reply",
        "parent_id": "nonexistent"
    })
    assert status == 404


# ---------------------------------------------------------------------------
# POST /status
# ---------------------------------------------------------------------------

def test_post_status_approved():
    status, body = _post("/status", {"status": "approved"})
    assert status == 200
    assert body["status"] == "approved"
    _, snap = _get("/comments")
    assert snap["status"] == "approved"


def test_post_status_changes_requested():
    status, body = _post("/status", {"status": "changes_requested"})
    assert status == 200
    assert body["status"] == "changes_requested"


def test_post_status_invalid_value_returns_400():
    status, body = _post("/status", {"status": "maybe"})
    assert status == 400


# ---------------------------------------------------------------------------
# POST /resolve
# ---------------------------------------------------------------------------

def test_post_resolve_marks_resolved():
    c = state.add_comment("a.py", 1, "thing")
    status, body = _post("/resolve", {"id": c["id"]})
    assert status == 200
    assert body["resolved"] is True


def test_post_resolve_nonexistent_returns_404():
    status, body = _post("/resolve", {"id": "ghost"})
    assert status == 404


# ---------------------------------------------------------------------------
# POST /approve-file
# ---------------------------------------------------------------------------

def test_post_approve_file_succeeds():
    with state.lock:
        state.diff_data = {"files": [{"filename": "a.py"}]}
    status, body = _post("/approve-file", {"file": "a.py"})
    assert status == 200
    assert "a.py" in body["approved_files"]


def test_post_approve_file_missing_field_returns_400():
    status, body = _post("/approve-file", {})
    assert status == 400


def test_post_approve_file_with_unresolved_returns_400():
    state.add_comment("a.py", 1, "issue")
    status, body = _post("/approve-file", {"file": "a.py"})
    assert status == 400


# ---------------------------------------------------------------------------
# PUT /comments/<id>
# ---------------------------------------------------------------------------

def test_put_comment_updates_text():
    c = state.add_comment("a.py", 1, "original")
    status, body = _put(f"/comments/{c['id']}", {"comment": "updated"})
    assert status == 200
    assert body["comment"] == "updated"


def test_put_comment_missing_text_returns_400():
    c = state.add_comment("a.py", 1, "original")
    status, body = _put(f"/comments/{c['id']}", {})
    assert status == 400


def test_put_comment_nonexistent_returns_404():
    status, body = _put("/comments/ghost", {"comment": "text"})
    assert status == 404


def test_put_comment_after_approved_returns_400():
    c = state.add_comment("a.py", 1, "issue")
    state.set_status("approved")
    status, body = _put(f"/comments/{c['id']}", {"comment": "edit"})
    assert status == 400


# ---------------------------------------------------------------------------
# DELETE /comments/<id>
# ---------------------------------------------------------------------------

def test_delete_comment_removes_it():
    c = state.add_comment("a.py", 1, "to remove")
    status, body = _delete(f"/comments/{c['id']}")
    assert status == 200
    assert body["id"] == c["id"]
    _, snap = _get("/comments")
    assert snap["comments"] == []


def test_delete_comment_nonexistent_returns_404():
    status, body = _delete("/comments/ghost")
    assert status == 404


def test_delete_comment_after_approved_returns_400():
    c = state.add_comment("a.py", 1, "issue")
    state.set_status("approved")
    status, body = _delete(f"/comments/{c['id']}")
    assert status == 400


# ---------------------------------------------------------------------------
# OPTIONS (CORS preflight)
# ---------------------------------------------------------------------------

def test_options_returns_204():
    conn = _conn()
    conn.request("OPTIONS", "/comments")
    resp = conn.getresponse()
    assert resp.status == 204
