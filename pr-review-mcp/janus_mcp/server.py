import json
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import anyio
from mcp.server.fastmcp import FastMCP

from janus_mcp._git import _validate_ref
from janus_mcp.ai import _run_ai_pre_review, _suggest_commit_message
from janus_mcp.diff_parser import parse_diff
from janus_mcp.http_server import find_free_port, run_http_server
from janus_mcp.state import state

mcp = FastMCP("pr-review")

_COMMENT_FIELDS = {"id", "file", "line", "comment", "resolved"}


def _slim_snapshot(snap: dict) -> dict:
    """Strip internal-only comment fields before returning to Claude."""
    slim = dict(snap)
    slim["comments"] = [
        {k: v for k, v in c.items() if k in _COMMENT_FIELDS}
        for c in snap.get("comments", [])
    ]
    return slim


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

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
    for file_info in diff_data.get("files", []):
        lc = subprocess.run(
            ["git", "show", f"{head_ref}:{file_info['filename']}"],
            capture_output=True, text=True
        )
        file_info["total_lines"] = len(lc.stdout.splitlines()) if lc.returncode == 0 else None
    state.new_round()
    with state.lock:
        state.diff_data = diff_data

    if ai_pre_review:
        threading.Thread(target=_run_ai_pre_review, args=(raw,), daemon=True).start()

    url = f"http://localhost:{state.port}"
    webbrowser.open(url)
    return {"url": url, "files_changed": len(diff_data.get("files", [])), "port": state.port}


@mcp.tool()
async def wait_for_approval(timeout_seconds: int = 86400) -> dict:
    """Block until the user approves or requests changes. Call immediately after create_review()."""
    deadline = time.time() + timeout_seconds
    last_keepalive = time.time()
    keepalive_interval = 300
    while time.time() < deadline:
        snap = state.snapshot()
        if snap["status"] in ("approved", "changes_requested"):
            if snap["status"] == "approved":
                with state.lock:
                    diff_text = state.diff_data.get("_raw", "")
                suggested = _suggest_commit_message(diff_text) if diff_text else None
                if suggested:
                    snap["suggested_message"] = suggested
            return _slim_snapshot(snap)
        now = time.time()
        if now - last_keepalive >= keepalive_interval:
            elapsed = int(now - (deadline - timeout_seconds))
            print(f"[wait_for_approval] still waiting... ({elapsed}s elapsed)", file=sys.stderr, flush=True)
            last_keepalive = now
        await anyio.sleep(2)
    return {"error": f"Timed out after {timeout_seconds}s", "status": "timeout"}


@mcp.tool()
def get_comments() -> dict:
    """Return current comments and review status."""
    return _slim_snapshot(state.snapshot())


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

    result = subprocess.run(["git", "add", "-A"], capture_output=True, text=True)
    if result.returncode != 0:
        return {"error": "git add failed: " + result.stderr.strip()}

    result = subprocess.run(["git", "commit", "-m", message], capture_output=True, text=True)
    if result.returncode != 0:
        return {"error": "git commit failed: " + result.stderr.strip()}

    commit_hash = ""
    for line in result.stdout.splitlines():
        if "]" in line:
            parts = line.split("]")
            if parts:
                commit_hash = parts[0].split("[")[-1].strip().split()[-1]
            break

    _persist_review(commit_hash, message, snap)
    return {"ok": True, "commit": commit_hash, "message": message}


# ---------------------------------------------------------------------------
# Review history
# ---------------------------------------------------------------------------

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
        print(f"WARNING: failed to persist review history: {e}", file=sys.stderr, flush=True)


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
def get_review(commit_hash: str, include_diff: bool = False) -> dict:
    """Return the review record for a specific commit hash. Set include_diff=True to include the raw diff data."""
    path = _history_dir() / f"{commit_hash}.json"
    if not path.exists():
        return {"error": f"No review found for commit: {commit_hash}"}
    data = json.loads(path.read_text())
    if not include_diff:
        data.pop("raw_diff", None)
    return data


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
        print(f"WARNING: port {desired} already in use, falling back to {fallback}", file=sys.stderr, flush=True)
        return fallback


def _start_hot_reload_watcher():
    """Poll server.py for changes and restart the process when it's modified.

    Only active when PR_REVIEW_HOT_RELOAD=1 is set. Off by default because
    os.execv kills the MCP stdio connection, requiring a manual /mcp reconnect.
    index.html is read from disk on every request, so UI changes never need this.
    """
    if not os.environ.get("PR_REVIEW_HOT_RELOAD"):
        return

    path = Path(__file__).resolve()
    last_mtime = path.stat().st_mtime

    def _watch():
        nonlocal last_mtime
        while True:
            time.sleep(1)
            try:
                mtime = path.stat().st_mtime
                if mtime != last_mtime:
                    print("\n[hot-reload] server.py changed — restarting process.", file=sys.stderr, flush=True)
                    print("[hot-reload] Run /mcp in Claude Code to reconnect.\n", file=sys.stderr, flush=True)
                    time.sleep(0.3)
                    os.execv(sys.executable, [sys.executable] + sys.argv)
            except Exception:
                pass

    threading.Thread(target=_watch, daemon=True).start()


def main():
    state.port = _resolve_port()
    http_thread = threading.Thread(target=run_http_server, args=(state.port,), daemon=True)
    http_thread.start()
    _start_hot_reload_watcher()
    mcp.run()


if __name__ == "__main__":
    main()
