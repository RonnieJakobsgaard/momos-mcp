"""UI tests — inline comment form, submit, resolve."""


def test_click_line_opens_comment_form(ui_page):
    ui_page.locator("td[data-file]").first.click()
    assert ui_page.locator(".comment-form-row").is_visible()


def test_cancel_closes_comment_form(ui_page):
    ui_page.locator("td[data-file]").first.click()
    ui_page.locator(".btn-cancel").click()
    assert ui_page.locator(".comment-form-row").count() == 0


def test_submit_comment_posts_and_renders(ui_page):
    ui_page.locator("td[data-file]").first.click()
    ui_page.locator(".comment-form-row textarea").fill("this needs a fix")
    ui_page.locator(".btn-submit").click()
    ui_page.wait_for_selector(".comment-thread", timeout=5000)
    assert "this needs a fix" in ui_page.locator(".comment-thread").first.inner_text()


def test_submitted_comment_appears_in_overview(ui_page):
    ui_page.locator("td[data-file]").first.click()
    ui_page.locator(".comment-form-row textarea").fill("overview comment")
    ui_page.locator(".btn-submit").click()
    ui_page.wait_for_selector(".comment-thread", timeout=5000)
    ui_page.locator("#btn-tab-overview").click()
    assert "overview comment" in ui_page.locator("#overview-file-list").inner_text()


def test_clicking_different_line_closes_old_form(ui_page):
    cells = ui_page.locator("td[data-file]").all()
    cells[0].click()
    assert ui_page.locator(".comment-form-row").count() == 1
    cells[1].click()
    assert ui_page.locator(".comment-form-row").count() == 1
