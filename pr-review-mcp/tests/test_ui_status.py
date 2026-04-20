"""UI tests — approve, request changes, unsaved comment warning."""


def test_approve_updates_status_badge(ui_page):
    ui_page.locator("#btn-approve").click()
    ui_page.wait_for_function("document.getElementById('status-badge').textContent.includes('Approved')", timeout=5000)
    assert "Approved" in ui_page.locator("#status-badge").inner_text()


def test_approve_disables_buttons(ui_page):
    ui_page.locator("#btn-approve").click()
    ui_page.wait_for_function("document.getElementById('btn-approve').disabled", timeout=5000)
    assert ui_page.locator("#btn-approve").is_disabled()
    assert ui_page.locator("#btn-changes").is_disabled()


def test_request_changes_updates_status_badge(ui_page):
    ui_page.locator("#btn-changes").click()
    ui_page.wait_for_function(
        "document.getElementById('status-badge').textContent.toLowerCase().includes('changes')",
        timeout=5000
    )
    badge = ui_page.locator("#status-badge").inner_text()
    assert badge  # badge updated


def test_approve_with_unsaved_text_shows_warning(ui_page):
    # Fill general comment textarea (visible on overview tab)
    ui_page.locator("#btn-tab-overview").click()
    ui_page.locator("#general-comment-input").fill("forgot to submit this")
    ui_page.locator("#btn-approve").click()
    assert ui_page.locator("#unsaved-warning").is_visible()


def test_unsaved_warning_proceed_submits_status(ui_page):
    ui_page.locator("#btn-tab-overview").click()
    ui_page.locator("#general-comment-input").fill("unsaved")
    ui_page.locator("#btn-approve").click()
    ui_page.locator("#unsaved-proceed").click()
    ui_page.wait_for_function("document.getElementById('btn-approve').disabled", timeout=5000)
    assert ui_page.locator("#btn-approve").is_disabled()


def test_unsaved_warning_dismiss_does_not_submit(ui_page):
    ui_page.locator("#btn-tab-overview").click()
    ui_page.locator("#general-comment-input").fill("unsaved")
    ui_page.locator("#btn-approve").click()
    # Dismiss via × button
    ui_page.locator("#unsaved-warning button[onclick]").click()
    assert not ui_page.locator("#btn-approve").is_disabled()
    assert not ui_page.locator("#unsaved-warning").is_visible()


def test_unsaved_warning_hides_when_textarea_cleared(ui_page):
    ui_page.locator("#btn-tab-overview").click()
    textarea = ui_page.locator("#general-comment-input")
    textarea.fill("something")
    ui_page.locator("#btn-approve").click()
    assert ui_page.locator("#unsaved-warning").is_visible()
    textarea.fill("")
    ui_page.wait_for_function(
        "document.getElementById('unsaved-warning').classList.contains('hidden')",
        timeout=3000
    )
    assert not ui_page.locator("#unsaved-warning").is_visible()
