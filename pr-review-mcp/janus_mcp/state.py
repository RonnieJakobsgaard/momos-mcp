import json
import os
import tempfile
import threading
import uuid


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

    def new_round(self):
        """Start a new review round: reset status and approved files, keep comments."""
        with self.lock:
            self.status = "pending"
            self.approved_files = set()
            self._write_comments()

    def add_comment(self, file: str, line: int, comment: str,
                    parent_id: str | None = None, source: str = "human",
                    side: str = "left",
                    comment_type: str = "suggestion") -> dict | str:
        with self.lock:
            if parent_id is not None:
                if not any(c["id"] == parent_id for c in self.comments):
                    return f"parent comment '{parent_id}' not found"
            entry = {
                "id": str(uuid.uuid4()), "file": file, "line": line,
                "comment": comment, "resolved": False, "parent_id": parent_id,
                "source": source, "side": side,
                "comment_type": comment_type if not parent_id else None,
            }
            self.comments.append(entry)
            self._write_comments()
        return entry

    def resolve_comment(self, comment_id: str) -> dict | None:
        with self.lock:
            for c in self.comments:
                if c["id"] == comment_id:
                    c["resolved"] = True
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
