import http.server
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import uuid
import webbrowser
from pathlib import Path

import anyio

try:
    import anthropic as _anthropic
    _HAS_ANTHROPIC = True
except ImportError:
    _HAS_ANTHROPIC = False

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

class SharedState:
    def __init__(self):
        self.lock = threading.Lock()
        self.comments: list[dict] = []
        self.status: str = "pending"
        self.diff_data: dict = {}
        self.approved_files: set[str] = set()
        self.port: int = 0
        self.temp_dir: str = tempfile.mkdtemp(prefix="pr-review-")

    @property
    def comments_path(self) -> str:
        return os.path.join(self.temp_dir, "comments.json")

    def _write_comments(self):
        """Must be called while holding self.lock."""
        with open(self.comments_path, "w") as f:
            json.dump({"status": self.status, "comments": self.comments}, f, indent=2)

    def reset(self):
        with self.lock:
            self.comments = []
            self.status = "pending"
            self.approved_files = set()
            self._write_comments()

    def add_comment(self, file: str, line: int, comment: str,
                    parent_id: str | None = None, source: str = "human",
                    side: str = "left") -> dict | str:
        with self.lock:
            if parent_id is not None:
                if not any(c["id"] == parent_id for c in self.comments):
                    return f"parent comment '{parent_id}' not found"
            entry = {
                "id": str(uuid.uuid4()), "file": file, "line": line,
                "comment": comment, "resolved": False, "parent_id": parent_id,
                "source": source, "side": side,
            }
            self.comments.append(entry)
            self._write_comments()
        return entry

    def resolve_comment(self, comment_id: str) -> dict | None:
        with self.lock:
            for c in self.comments:
                if c["id"] == comment_id:
                    c["resolved"] = True
                    # Resolve all replies to this comment too
                    for reply in self.comments:
                        if reply.get("parent_id") == comment_id:
                            reply["resolved"] = True
                    self._write_comments()
                    return c
        return None

    def update_comment(self, comment_id: str, text: str) -> dict | None | str:
        """Returns updated comment, None if not found, or an error string."""
        with self.lock:
            if self.status != "pending":
                return "cannot edit comments after review is submitted"
            for c in self.comments:
                if c["id"] == comment_id:
                    if c["resolved"]:
                        return "cannot edit a resolved comment"
                    c["comment"] = text
                    self._write_comments()
                    return dict(c)
        return None

    def delete_comment(self, comment_id: str) -> dict | None | str:
        """Returns deleted comment, None if not found, or an error string."""
        with self.lock:
            if self.status != "pending":
                return "cannot delete comments after review is submitted"
            for i, c in enumerate(self.comments):
                if c["id"] == comment_id:
                    if c["resolved"]:
                        return "cannot delete a resolved comment"
                    removed = self.comments.pop(i)
                    self._write_comments()
                    return dict(removed)
        return None

    def set_status(self, status: str):
        with self.lock:
            self.status = status
            self._write_comments()

    def approve_file(self, filename: str) -> dict | str:
        """Returns updated approved_files list, or an error string."""
        with self.lock:
            unresolved = [c for c in self.comments if c["file"] == filename and not c["resolved"]]
            if unresolved:
                return f"file '{filename}' has {len(unresolved)} unresolved comment(s)"
            self.approved_files.add(filename)
            all_files = {f["filename"] for f in self.diff_data.get("files", [])}
            if all_files and all_files <= self.approved_files:
                self.status = "approved"
                self._write_comments()
            return {"approved_files": sorted(self.approved_files), "status": self.status}

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "status": self.status,
                "comments": list(self.comments),
                "approved_files": sorted(self.approved_files),
            }


state = SharedState()

# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class ReviewHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # suppress default request logging

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, body: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/":
            index = Path(__file__).parent / "index.html"
            if index.exists():
                self._send_html(index.read_bytes())
            else:
                self._send_html(b"<h1>index.html not found</h1>")
        elif self.path == "/diff":
            with state.lock:
                self._send_json(state.diff_data)
        elif self.path == "/comments":
            self._send_json(state.snapshot())
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        body = self._read_body()

        if self.path == "/comments":
            file = body.get("file", "")
            line = int(body.get("line", 0))
            comment = body.get("comment", "")
            if not comment:
                self._send_json({"error": "comment required"}, 400)
                return
            parent_id = body.get("parent_id") or None
            side = body.get("side", "left")
            entry = state.add_comment(file, line, comment, parent_id, side=side)
            if isinstance(entry, str):
                self._send_json({"error": entry}, 404)
                return
            self._send_json(entry, 201)

        elif self.path == "/status":
            status = body.get("status", "")
            if status not in ("approved", "changes_requested"):
                self._send_json({"error": "status must be 'approved' or 'changes_requested'"}, 400)
                return
            state.set_status(status)
            self._send_json({"ok": True, "status": status})

        elif self.path == "/resolve":
            comment_id = body.get("id", "")
            result = state.resolve_comment(comment_id)
            if result is None:
                self._send_json({"error": f"comment '{comment_id}' not found"}, 404)
            else:
                self._send_json(result)

        elif self.path == "/approve-file":
            filename = body.get("file", "").strip()
            if not filename:
                self._send_json({"error": "file required"}, 400)
                return
            result = state.approve_file(filename)
            if isinstance(result, str):
                self._send_json({"error": result}, 400)
            else:
                self._send_json(result)

        else:
            self._send_json({"error": "not found"}, 404)

    def do_PUT(self):
        body = self._read_body()
        if self.path.startswith("/comments/"):
            comment_id = self.path[len("/comments/"):]
            text = body.get("comment", "").strip()
            if not text:
                self._send_json({"error": "comment text required"}, 400)
                return
            result = state.update_comment(comment_id, text)
            if result is None:
                self._send_json({"error": f"comment '{comment_id}' not found"}, 404)
            elif isinstance(result, str):
                self._send_json({"error": result}, 400)
            else:
                self._send_json(result)
        else:
            self._send_json({"error": "not found"}, 404)

    def do_DELETE(self):
        if self.path.startswith("/comments/"):
            comment_id = self.path[len("/comments/"):]
            result = state.delete_comment(comment_id)
            if result is None:
                self._send_json({"error": f"comment '{comment_id}' not found"}, 404)
            elif isinstance(result, str):
                self._send_json({"error": result}, 400)
            else:
                self._send_json(result)
        else:
            self._send_json({"error": "not found"}, 404)


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


def run_http_server(port: int):
    with http.server.HTTPServer(("localhost", port), ReviewHandler) as httpd:
        httpd.serve_forever()


# ---------------------------------------------------------------------------
# MCP server + tools
# ---------------------------------------------------------------------------

mcp = FastMCP("pr-review")

_COMMIT_MSG_PROMPT = """\
Generate a conventional commit message for the git diff below.
Format: <type>(<optional scope>): <short imperative subject> (max 72 chars)

Types: feat, fix, refactor, style, test, docs, chore.
Output only the commit message — no explanation, no backticks, no blank lines.
"""


_AI_REVIEW_PROMPT = """\
You are a code reviewer. Analyze the git diff below and identify specific issues: bugs, logic errors, security problems, unclear variable names, or missing edge-case handling. Skip style nits and formatting.

For each issue, respond with a JSON object on its own line (NDJSON), with these fields:
  file    — the filename (must match exactly)
  line    — the new-file line number closest to the issue (integer)
  comment — a concise, actionable description of the issue (1–3 sentences)

If there are no issues, output an empty line. Do not include any prose outside the JSON lines.

Diff:
"""


def _run_ai_pre_review(diff_text: str) -> None:
    """Send the diff to Claude and inject any issues as AI-sourced comments."""
    if not _HAS_ANTHROPIC:
        print("WARNING: anthropic package not installed, skipping AI pre-review", flush=True)
        return
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("WARNING: ANTHROPIC_API_KEY not set, skipping AI pre-review", flush=True)
        return
    try:
        client = _anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=2048,
            system=[{
                "type": "text",
                "text": _AI_REVIEW_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{
                "type": "text",
                "text": diff_text,
                "cache_control": {"type": "ephemeral"},
            }] if False else [{"role": "user", "content": [
                {
                    "type": "text",
                    "text": diff_text,
                    "cache_control": {"type": "ephemeral"},
                }
            ]}],
        )
        text = response.content[0].text if response.content else ""
        injected = 0
        for raw_line in text.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                obj = json.loads(raw_line)
                file = str(obj.get("file", "")).strip()
                line = int(obj.get("line", 0))
                comment = str(obj.get("comment", "")).strip()
                if file and comment:
                    state.add_comment(file, line, comment, source="ai")
                    injected += 1
            except (json.JSONDecodeError, ValueError, KeyError):
                pass
        print(f"AI pre-review: injected {injected} comment(s)", flush=True)
    except Exception as e:
        print(f"WARNING: AI pre-review failed: {e}", flush=True)


def _suggest_commit_message(diff_text: str) -> str | None:
    """Return a suggested conventional commit message, or None on failure."""
    if not _HAS_ANTHROPIC:
        return None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        client = _anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=128,
            system=[{
                "type": "text",
                "text": _COMMIT_MSG_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": [
                {
                    "type": "text",
                    "text": diff_text,
                    "cache_control": {"type": "ephemeral"},
                }
            ]}],
        )
        text = response.content[0].text.strip() if response.content else ""
        return text or None
    except Exception as e:
        print(f"WARNING: commit message suggestion failed: {e}", flush=True)
        return None


def _validate_ref(ref: str) -> str | None:
    """Return None if ref is valid, or an error string if not."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", ref],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return f"invalid ref: {ref}"
    return None


@mcp.tool()
def create_review(base_ref: str = "main", head_ref: str = "HEAD", ai_pre_review: bool = False, title: str = "") -> dict:
    """Run git diff, parse it, serve the review UI, and open the browser."""
    for ref in (base_ref, head_ref):
        if err := _validate_ref(ref):
            return {"error": err}

    result = subprocess.run(
        ["git", "diff", base_ref, head_ref],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return {"error": result.stderr.strip() or "git diff failed"}

    raw = result.stdout
    if not raw.strip():
        return {"error": f"No changes found between {base_ref} and {head_ref}"}

    diff_data = parse_diff(raw)
    diff_data["base_ref"] = base_ref
    diff_data["head_ref"] = head_ref
    diff_data["title"] = title
    diff_data["_raw"] = raw
    state.reset()
    with state.lock:
        state.diff_data = diff_data

    if ai_pre_review:
        threading.Thread(target=_run_ai_pre_review, args=(raw,), daemon=True).start()

    url = f"http://localhost:{state.port}"
    webbrowser.open(url)
    return {"url": url, "files_changed": len(diff_data.get("files", [])), "port": state.port}


@mcp.tool()
async def wait_for_approval(timeout_seconds: int = 600) -> dict:
    """Block until the user approves or requests changes. Call immediately after create_review()."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        snap = state.snapshot()
        if snap["status"] in ("approved", "changes_requested"):
            if snap["status"] == "approved":
                with state.lock:
                    diff_text = state.diff_data.get("_raw", "")
                suggested = _suggest_commit_message(diff_text) if diff_text else None
                if suggested:
                    snap["suggested_message"] = suggested
            return snap
        await anyio.sleep(2)
    return {"error": f"Timed out after {timeout_seconds}s", "status": "timeout"}


@mcp.tool()
def get_comments() -> dict:
    """Return current comments and review status."""
    return state.snapshot()


@mcp.tool()
def mark_comment_resolved(comment_id: str) -> dict:
    """Mark a specific comment as resolved after fixing the issue."""
    result = state.resolve_comment(comment_id)
    if result is None:
        return {"error": f"Comment '{comment_id}' not found"}
    return result


@mcp.tool()
def approve_and_commit(message: str) -> dict:
    """Commit all changes. Only succeeds when all comments are resolved."""
    snap = state.snapshot()
    unresolved = [c for c in snap["comments"] if not c["resolved"]]
    if unresolved:
        ids = [c["id"] for c in unresolved]
        return {"error": "Unresolved comments remain", "unresolved_ids": ids}

    result = subprocess.run(
        ["git", "add", "-A"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return {"error": "git add failed: " + result.stderr.strip()}

    result = subprocess.run(
        ["git", "commit", "-m", message],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return {"error": "git commit failed: " + result.stderr.strip()}

    # Extract commit hash from output
    commit_hash = ""
    for line in result.stdout.splitlines():
        if "]" in line:
            parts = line.split("]")
            if parts:
                commit_hash = parts[0].split("[")[-1].strip().split()[-1]
            break

    _persist_review(commit_hash, message, snap)
    return {"ok": True, "commit": commit_hash, "message": message}


def _history_dir() -> Path:
    d = Path.home() / ".pr-review" / "history"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _persist_review(commit_hash: str, message: str, snap: dict):
    try:
        with state.lock:
            diff = dict(state.diff_data)
        record = {
            "commit": commit_hash,
            "message": message,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "base_ref": diff.get("base_ref", "main"),
            "head_ref": diff.get("head_ref", "HEAD"),
            "files": [f["filename"] for f in diff.get("files", [])],
            "comments": snap["comments"],
            "raw_diff": diff,
        }
        path = _history_dir() / f"{commit_hash}.json"
        path.write_text(json.dumps(record, indent=2))
    except Exception as e:
        print(f"WARNING: failed to persist review history: {e}", flush=True)


@mcp.tool()
def list_reviews() -> dict:
    """Return summaries of past review sessions, newest first."""
    try:
        records = []
        for path in sorted(_history_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text())
                records.append({
                    "commit": data.get("commit"),
                    "message": data.get("message"),
                    "timestamp": data.get("timestamp"),
                    "files_changed": len(data.get("files", [])),
                })
            except Exception:
                pass
        return {"reviews": records}
    except FileNotFoundError:
        return {"reviews": []}


@mcp.tool()
def get_review(commit_hash: str) -> dict:
    """Return the full review record for a specific commit hash."""
    path = _history_dir() / f"{commit_hash}.json"
    if not path.exists():
        return {"error": f"No review found for commit: {commit_hash}"}
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Diff parser
# ---------------------------------------------------------------------------

def parse_diff(raw: str) -> dict:
    files = []
    current_file = None
    current_hunk = None
    old_line = 0
    new_line = 0

    for line in raw.splitlines():
        if line.startswith("diff --git"):
            if current_file:
                if current_hunk:
                    current_file["hunks"].append(current_hunk)
                files.append(current_file)
            current_file = {"filename": "", "hunks": []}
            current_hunk = None

        elif line.startswith("--- "):
            pass  # handled by +++ line

        elif line.startswith("+++ ") and current_file is not None:
            name = line[4:]
            if name.startswith("b/"):
                name = name[2:]
            current_file["filename"] = name

        elif line.startswith("@@ ") and current_file is not None:
            if current_hunk:
                current_file["hunks"].append(current_hunk)
            # parse @@ -old_start,old_count +new_start,new_count @@
            parts = line.split(" ")
            old_part = parts[1]  # e.g. -10,5
            new_part = parts[2]  # e.g. +10,6
            old_line = abs(int(old_part.split(",")[0]))
            new_line = abs(int(new_part.split(",")[0]))
            current_hunk = {"header": line, "lines": []}

        elif current_hunk is not None:
            if line.startswith("+"):
                current_hunk["lines"].append({
                    "type": "add", "content": line[1:],
                    "old_line": None, "new_line": new_line
                })
                new_line += 1
            elif line.startswith("-"):
                current_hunk["lines"].append({
                    "type": "remove", "content": line[1:],
                    "old_line": old_line, "new_line": None
                })
                old_line += 1
            elif line.startswith("\\"):
                pass  # "No newline at end of file"
            else:
                current_hunk["lines"].append({
                    "type": "context", "content": line[1:],
                    "old_line": old_line, "new_line": new_line
                })
                old_line += 1
                new_line += 1

    if current_file:
        if current_hunk:
            current_file["hunks"].append(current_hunk)
        files.append(current_file)

    return {"files": files}


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def _resolve_port() -> int:
    desired = int(os.environ.get("PR_REVIEW_PORT", 7777))
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("localhost", desired))
        return desired
    except OSError:
        fallback = find_free_port()
        print(f"WARNING: port {desired} already in use, falling back to {fallback}", flush=True)
        return fallback

state.port = _resolve_port()
http_thread = threading.Thread(target=run_http_server, args=(state.port,), daemon=True)
http_thread.start()

if __name__ == "__main__":
    mcp.run()
