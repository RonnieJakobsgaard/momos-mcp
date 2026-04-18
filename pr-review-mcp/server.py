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
            self._write_comments()

    def add_comment(self, file: str, line: int, comment: str) -> dict:
        entry = {"id": str(uuid.uuid4()), "file": file, "line": line, "comment": comment, "resolved": False}
        with self.lock:
            self.comments.append(entry)
            self._write_comments()
        return entry

    def resolve_comment(self, comment_id: str) -> dict | None:
        with self.lock:
            for c in self.comments:
                if c["id"] == comment_id:
                    c["resolved"] = True
                    self._write_comments()
                    return c
        return None

    def set_status(self, status: str):
        with self.lock:
            self.status = status
            self._write_comments()

    def snapshot(self) -> dict:
        with self.lock:
            return {"status": self.status, "comments": list(self.comments)}


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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
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
            entry = state.add_comment(file, line, comment)
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


@mcp.tool()
def create_review(base_branch: str = "main") -> dict:
    """Run git diff, parse it, serve the review UI, and open the browser."""
    result = subprocess.run(
        ["git", "diff", base_branch],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return {"error": result.stderr.strip() or "git diff failed"}

    raw = result.stdout
    if not raw.strip():
        return {"error": "No changes found against branch: " + base_branch}

    diff_data = parse_diff(raw)
    state.reset()
    with state.lock:
        state.diff_data = diff_data

    url = f"http://localhost:{state.port}"
    webbrowser.open(url)
    return {"url": url, "files_changed": len(diff_data.get("files", [])), "port": state.port}


@mcp.tool()
def wait_for_approval(timeout_seconds: int = 600) -> dict:
    """Block until the user approves or requests changes. Call immediately after create_review()."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        snap = state.snapshot()
        if snap["status"] in ("approved", "changes_requested"):
            return snap
        time.sleep(2)
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

    return {"ok": True, "commit": commit_hash, "message": message}


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

state.port = find_free_port()
http_thread = threading.Thread(target=run_http_server, args=(state.port,), daemon=True)
http_thread.start()

if __name__ == "__main__":
    mcp.run()
