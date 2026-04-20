"""UI tests — expand context buttons (top/bottom of file)."""
import copy
import pytest
from janus_mcp.server import state


# Hunk covers lines 20-30 of server.py (tracked file).
# Lines 1-19 → expand-above button (19 > 3).
# Lines 31-727 → expand-below button.
_EXPAND_DIFF = {
    "base_ref": "main",
    "head_ref": "HEAD",
    "title": "",
    "_raw": "",
    "files": [
        {
            "filename": "pr-review-mcp/server.py",
            "total_lines": 727,
            "hunks": [
                {
                    "header": "@@ -20,11 +20,11 @@",
                    "lines": [
                        {"type": "context", "content": "# context", "old_line": i, "new_line": i}
                        for i in range(20, 31)
                    ],
                }
            ],
        }
    ],
}


@pytest.fixture
def expand_page(page):
    d = copy.deepcopy(_EXPAND_DIFF)
    # Add one changed line so diff2html renders something
    d["files"][0]["hunks"][0]["lines"][5] = {
        "type": "add", "content": "# changed line", "old_line": None, "new_line": 25,
    }
    with state.lock:
        state.diff_data = d
    page.goto(f"http://localhost:{state.port}")
    page.wait_for_selector(".d2h-file-wrapper", timeout=8000)
    yield page
    state.reset()
    with state.lock:
        state.diff_data = {}


def test_expand_above_button_present(expand_page):
    """Lines 1-19 are above the hunk → expand button should appear."""
    assert expand_page.locator(".expand-ctx-btn").count() >= 1


def test_expand_below_button_present(expand_page):
    """Lines 31-727 are below the hunk → expand button should appear."""
    assert expand_page.locator(".expand-ctx-btn").count() >= 1


def test_expand_buttons_show_hidden_line_count(expand_page):
    buttons = expand_page.locator(".expand-ctx-btn").all()
    for btn in buttons:
        text = btn.inner_text()
        assert "hidden" in text or "Load more" in text


def test_clicking_expand_loads_lines(expand_page):
    btn = expand_page.locator(".expand-ctx-btn").first
    initial_rows = expand_page.locator(".expand-ctx-line").count()
    btn.click()
    expand_page.wait_for_function(
        f"document.querySelectorAll('.expand-ctx-line').length > {initial_rows}",
        timeout=5000
    )
    assert expand_page.locator(".expand-ctx-line").count() > initial_rows


def test_expand_loads_at_most_15_lines_per_click(expand_page):
    # Switch to unified so rows are only inserted into one table
    expand_page.locator("#btn-fmt-unified").click()
    expand_page.wait_for_selector(".d2h-diff-table")
    btn = expand_page.locator(".expand-ctx-btn").first
    btn.click()
    expand_page.wait_for_function(
        "document.querySelectorAll('.expand-ctx-line').length > 0",
        timeout=5000
    )
    assert expand_page.locator(".expand-ctx-line").count() <= 15


def test_no_expand_button_when_hunk_covers_full_file(page):
    """Hunk starts at line 1 and total_lines == last hunk line → no expand buttons."""
    d = {
        "base_ref": "main", "head_ref": "HEAD", "title": "", "_raw": "",
        "files": [{
            "filename": "foo.py",
            "total_lines": 5,
            "hunks": [{
                "header": "@@ -1,5 +1,5 @@",
                "lines": [
                    {"type": "context", "content": f"line {i}", "old_line": i, "new_line": i}
                    for i in range(1, 6)
                ],
            }],
        }],
    }
    with state.lock:
        state.diff_data = d
    page.goto(f"http://localhost:{state.port}")
    page.wait_for_selector(".d2h-file-wrapper", timeout=8000)
    assert page.locator(".expand-ctx-btn").count() == 0
    state.reset()
    with state.lock:
        state.diff_data = {}


def test_side_by_side_shows_only_one_expand_button_per_gap(expand_page):
    """In side-by-side mode, only the left table gets the button (not both)."""
    expand_page.locator("#btn-fmt-side").click()
    expand_page.wait_for_selector(".d2h-file-side-diff")
    # Each gap should have exactly one visible button, not two
    buttons = expand_page.locator(".expand-ctx-btn").all()
    # Both top and bottom gaps = 2 buttons max for this diff
    assert len(buttons) <= 2
