"""Smoke tests — page loads and basic elements present."""


def test_page_title(ui_page):
    assert ui_page.title() == "PR Review"


def test_status_badge_shows_pending(ui_page):
    badge = ui_page.locator("#status-badge")
    assert badge.is_visible()
    assert "Pending" in badge.inner_text()


def test_approve_button_visible(ui_page):
    assert ui_page.locator("#btn-approve").is_visible()


def test_request_changes_button_visible(ui_page):
    assert ui_page.locator("#btn-changes").is_visible()


def test_unsaved_warning_hidden_initially(ui_page):
    assert not ui_page.locator("#unsaved-warning").is_visible()
