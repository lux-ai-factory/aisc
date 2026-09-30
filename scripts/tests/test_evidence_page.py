"""Collect evidence, the page (evidence links plan 2026-09-30, step B). Step 4 of the project page
opens it; it links the objectives selected in step 2 to the tests and controls installed in step 3
through the platform, and has the two ways on to the engine and the controls app. Static checks of
the page source, like test_connections_page.py."""
import re

from conftest import ROOT

PAGE = ROOT / "homepage/evidence.html"
PROJECT_PAGE = ROOT / "homepage/project.html"


def read(path):
    assert path.is_file(), f"missing feature: {path.relative_to(ROOT)} does not exist"
    return path.read_text()


def script_of(html):
    return "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S | re.I))


def markup_of(html):
    return re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)


# ── step 4 on the project page ──────────────────────────────────────────────

def test_step_4_is_one_card_that_opens_the_evidence_page():
    html = read(PROJECT_PAGE)
    card = re.search(r'<a\b[^>]*id="evidence-card"[^>]*>(.*?)</a>', html, re.S)
    assert card, "step 4 is not a link"
    assert "<h2>Collect evidence</h2>" in card.group(1)
    assert re.search(r'<span class="n">4</span>', card.group(1))
    assert re.search(r"getElementById\('evidence-card'\)\.href\s*=\s*'/evidence\.html\?project='\s*\+\s*"
                     r"encodeURIComponent\(slug\)", script_of(html))


def test_the_two_links_moved_to_the_evidence_page():
    html = read(PROJECT_PAGE)
    assert 'id="controls-card"' not in html and 'id="engine-card"' not in html
    # the catalogue still learns where the controls app is, from the step 4 card
    assert 'data-controls="http://localhost/controls"' in html
    assert "dataset.controls" in script_of(html)


# ── the page ────────────────────────────────────────────────────────────────

def test_the_page_has_the_launchers_look_and_one_inline_script():
    html, reference = read(PAGE), read(PROJECT_PAGE)
    for var in re.findall(r"(--[a-z0-9-]+)\s*:", re.search(r":root\s*\{(.*?)\}", reference, re.S).group(1)):
        assert re.search(re.escape(var) + r"\s*:", html), var
    assert 'class="session"' in html and 'id="who"' in html
    scripts = re.findall(r"<script\b([^>]*)>", html, re.I)
    assert len(scripts) == 1 and "src" not in scripts[0].lower()
    assert re.search(r"<title>Collect evidence\b", html)


def test_it_has_the_two_buttons_into_the_project():
    html = read(PAGE)
    markup, script = markup_of(html), script_of(html)
    for id_, label in (("execute-tests", "Execute tests"), ("address-controls", "Address controls")):
        link = re.search(r'<a\b[^>]*id="' + id_ + r'"[^>]*>(.*?)</a>', markup, re.S)
        assert link and label in link.group(1), id_
    assert re.search(r"\$\('execute-tests'\)\.href\s*=\s*'http://localhost/\?project='\s*\+\s*enc\(p\.pid\)", script)
    assert re.search(r"\$\('address-controls'\)\.href\s*=\s*'http://localhost/controls/p/'\s*\+\s*enc\(p\.pid\)",
                     script)


def test_it_reads_and_saves_the_links_through_the_platform():
    script = script_of(read(PAGE))
    assert "'/api/projects/' + enc(slug) + '/evidence'" in script
    assert "'/api/projects/' + enc(slug) + '/evidence/links'" in script
    assert "method: 'PUT'" in script
    for field in ("objective_id", "kind", "key", "can_edit", "stale"):
        assert field in script, field


def test_objectives_are_named_by_the_platform():
    # the page is on the launcher's origin; the platform reads the catalogue for it
    script = script_of(read(PAGE))
    assert "o.title" in script and "/control-objectives/" not in script


def test_a_viewer_sees_the_grid_but_cannot_change_it():
    script = script_of(read(PAGE))
    assert re.search(r"disabled\s*=\s*!data\.can_edit", script) or re.search(r"!data\.can_edit", script)
    assert "$('save').hidden = !data.can_edit" in script


def test_a_stale_cell_takes_no_new_link_but_keeps_an_old_one():
    script = script_of(read(PAGE))
    # a box is disabled when its row or column is stale and it is not already ticked
    assert re.search(r"box\.disabled\s*=\s*!data\.can_edit\s*\|\|\s*\(\s*stale\s*&&\s*!box\.checked\s*\)", script)


def test_an_objective_with_nothing_linked_says_not_covered():
    assert "not covered" in script_of(read(PAGE))
