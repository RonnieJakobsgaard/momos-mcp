"""UI tests — diff rendering, file tree, format toggle."""


def test_file_tree_shows_both_files(ui_page):
    labels = ui_page.locator("#file-list a span.truncate").all()
    names = [l.inner_text() for l in labels]
    assert "foo.py" in names
    assert "bar.py" in names


def test_diff_container_has_code_cells(ui_page):
    # td[data-file] is set on every clickable code cell after rendering
    assert ui_page.locator("td[data-file]").count() > 0


def test_side_by_side_renders_two_panes(ui_page):
    # Default format is side-by-side
    ui_page.locator("#btn-fmt-side").click()
    ui_page.wait_for_selector(".d2h-file-side-diff")
    assert ui_page.locator(".d2h-file-side-diff").count() >= 2


def test_switch_to_unified_removes_side_panes(ui_page):
    ui_page.locator("#btn-fmt-unified").click()
    ui_page.wait_for_selector(".d2h-diff-table")
    assert ui_page.locator(".d2h-file-side-diff").count() == 0


def test_unified_renders_diff_table(ui_page):
    ui_page.locator("#btn-fmt-unified").click()
    ui_page.wait_for_selector(".d2h-diff-table")
    assert ui_page.locator(".d2h-diff-table").count() > 0


def test_ref_range_shown_in_header(ui_page):
    ref = ui_page.locator("#ref-range")
    assert "main" in ref.inner_text()
    assert "HEAD" in ref.inner_text()


def test_overview_tab_switches_panel(ui_page):
    ui_page.locator("#btn-tab-overview").click()
    assert ui_page.locator("#overview-panel").is_visible()
    assert not ui_page.locator("#diff-panel").is_visible()


def test_diff_tab_switches_back(ui_page):
    ui_page.locator("#btn-tab-overview").click()
    ui_page.locator("#btn-tab-diff").click()
    assert ui_page.locator("#diff-panel").is_visible()
    assert not ui_page.locator("#overview-panel").is_visible()
