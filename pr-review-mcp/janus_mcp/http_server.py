import http.server
import json
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from janus_mcp._git import _validate_ref
from janus_mcp.state import state


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
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
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
        elif self.path.startswith("/file-lines"):
            params = parse_qs(urlparse(self.path).query)
            filepath = params.get("file", [""])[0].strip()
            start = max(1, int(params.get("start", ["1"])[0]))
            end_param = params.get("end", [None])[0]
            end = int(end_param) if end_param else None
            ref = params.get("ref", ["HEAD"])[0].strip()
            if not filepath:
                self._send_json({"error": "file required"}, 400)
                return
            err = _validate_ref(ref)
            if err:
                self._send_json({"error": err}, 400)
                return
            result = subprocess.run(
                ["git", "show", f"{ref}:{filepath}"],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                self._send_json({"error": f"could not read {filepath} at {ref}"}, 404)
                return
            all_lines = result.stdout.splitlines()
            total = len(all_lines)
            actual_end = min(end if end is not None else total, total)
            selected = [
                {"line_no": i + 1, "content": all_lines[i]}
                for i in range(start - 1, actual_end)
            ]
            self._send_json({"lines": selected, "total_lines": total})
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
            comment_type = body.get("comment_type", "suggestion")
            if comment_type not in ("nitpick", "suggestion", "blocker"):
                comment_type = "suggestion"
            entry = state.add_comment(file, line, comment, parent_id, side=side, comment_type=comment_type)
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
