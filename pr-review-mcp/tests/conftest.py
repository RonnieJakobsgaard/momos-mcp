import sys
import os
import copy
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server import state

# ---------------------------------------------------------------------------
# Synthetic diff used by UI tests
# ---------------------------------------------------------------------------

_BASE_DIFF = {
    "base_ref": "main",
    "head_ref": "HEAD",
    "title": "Test Review",
    "_raw": "",
    "files": [
        {
            "filename": "foo.py",
            "total_lines": 50,
            "hunks": [
                {
                    "header": "@@ -5,4 +5,5 @@",
                    "lines": [
                        {"type": "context", "content": "def hello():", "old_line": 5, "new_line": 5},
                        {"type": "remove", "content": "    return None", "old_line": 6, "new_line": None},
                        {"type": "add",    "content": "    return 'hello'", "old_line": None, "new_line": 6},
                        {"type": "context", "content": "", "old_line": 7, "new_line": 7},
                    ],
                }
            ],
        },
        {
            "filename": "bar.py",
            "total_lines": 30,
            "hunks": [
                {
                    "header": "@@ -10,3 +10,4 @@",
                    "lines": [
                        {"type": "context", "content": "x = 1", "old_line": 10, "new_line": 10},
                        {"type": "add",    "content": "y = 2", "old_line": None, "new_line": 11},
                        {"type": "context", "content": "z = 3", "old_line": 11, "new_line": 12},
                    ],
                }
            ],
        },
    ],
}


@pytest.fixture
def mock_diff():
    """Load synthetic diff into server state; reset after test."""
    d = copy.deepcopy(_BASE_DIFF)
    with state.lock:
        state.diff_data = d
    yield d
    state.reset()
    with state.lock:
        state.diff_data = {}


@pytest.fixture
def ui_page(page, mock_diff):
    """Playwright page pre-loaded with the review UI and mock diff data."""
    page.goto(f"http://localhost:{state.port}")
    page.wait_for_selector(".d2h-file-wrapper", timeout=8000)
    return page
