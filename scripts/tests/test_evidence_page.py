"""The AI Assessment Sandbox page (evidence.html). The project page's sandbox card opens it; it has the
three ways on (the engine, the controls app, the dashboard) with their tiles. Its tables linking tests and
controls to the control objectives were removed on 2026-10-04 (the platform keeps the links, the report
composer reads them). Static checks of the page source, like test_connections_page.py."""
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

def test_the_sandbox_card_opens_this_page():
    """2026-10-03: the project page's sandbox card (test_project_page_sandbox.py) opens this page."""
    html = read(PROJECT_PAGE)
    card = re.search(r'<a\b[^>]*id="sandbox-card"[^>]*>(.*?)</a>', html, re.S)
    assert card and "<h2>AI Assessment Sandbox</h2>" in card.group(1)
    assert re.search(r"getElementById\('sandbox-card'\)\.href\s*=\s*'/evidence\.html\?project='\s*\+\s*"
                     r"encodeURIComponent\(slug\)", script_of(html))


def test_the_two_links_moved_to_the_evidence_page():
    html = read(PROJECT_PAGE)
    assert 'id="controls-card"' not in html and 'id="engine-card"' not in html
    # the catalogue still learns where the controls app is, from the sandbox card
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
    assert re.search(r"<title>AI Assessment Sandbox\b", html)


def test_it_has_the_two_buttons_into_the_project():
    html = read(PAGE)
    markup, script = markup_of(html), script_of(html)
    for id_, label in (("execute-tests", "Execute tests"), ("address-controls", "Address controls")):
        link = re.search(r'<a\b[^>]*id="' + id_ + r'"[^>]*>(.*?)</a>', markup, re.S)
        assert link and label in link.group(1), id_
    assert re.search(r"\$\('execute-tests'\)\.href\s*=\s*'http://localhost/\?project='\s*\+\s*enc\(p\.pid\)", script)
    assert re.search(r"\$\('address-controls'\)\.href\s*=\s*'http://localhost/controls/p/'\s*\+\s*enc\(p\.pid\)",
                     script)


# ── helpers for the CSS ──

def style_of(html):
    return "\n".join(re.findall(r"<style\b[^>]*>(.*?)</style>", html, re.S | re.I))


def rule(css, selector):
    m = re.search(r"(?:^|[}\s])" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"no CSS rule for {selector}"
    return m.group(1)


# ── step 4 tidied (2026-10-02) ──────────────────────────────────────────────

def test_the_two_ways_on_are_big_buttons_with_nothing_else():
    html = read(PAGE)
    markup, css = markup_of(html), style_of(html)
    assert re.search(r'<a class="way" id="execute-tests" href="[^"]+">Execute tests</a>', markup)
    assert re.search(r'<a class="way" id="address-controls" href="[^"]+">Address controls</a>', markup)
    assert "<small>" not in markup and "Run the tests in the execution engine" not in markup
    way = rule(css, "a.way")
    # bigger since 2026-10-03 (the test tiles sit under Execute tests)
    assert re.search(r"font-size\s*:\s*(1[4-9]|2\d)px", way) and re.search(r"padding\s*:\s*(1[6-9]|[2-4]\d)px", way)


# ── one AI card version at a time (2026-10-02) ───────────────────────────────

def test_the_page_names_its_card_version_and_offers_the_others():
    html = read(PAGE)
    markup, script = markup_of(html), script_of(html)
    assert re.search(r'<select class="version" id="version"', markup)
    assert "var all = data.versions || [];" in script and "all.forEach(" in script and "data.version" in script
    # the version asked for travels in the address and to the platform
    assert "params.get('version')" in script
    assert "'/evidence' + (version ? '?version=' + enc(version) : '')" in script


def test_hidden_means_hidden_whatever_an_elements_display():
    # a `button { display: ... }` rule otherwise beats the hidden attribute: Save showed on a
    # read-only version, and to a viewer (2026-10-02)
    css = style_of(read(PAGE))
    assert re.search(r"\[hidden\]\s*\{\s*display\s*:\s*none\s*!important", css)


# ── step 4 test tiles (2026-10-03) ──────────────────────────────────────────

def test_the_tests_tiles_are_a_column_under_execute_tests():
    markup = markup_of(read(PAGE))
    column = re.search(r'<div class="way-col">\s*(<a\b[^>]*id="execute-tests".*?</a>)\s*'
                       r'<div class="tiles" id="test-tiles"', markup, re.S)
    assert column, "the tiles do not sit under Execute tests"
    assert re.search(r'<div class="way-col">\s*<a\b[^>]*id="address-controls"', markup)


def test_the_two_buttons_are_bigger():
    html = read(PAGE)
    way = re.search(r"a\.way\{(.*?)\}", html, re.S).group(1)
    size = re.search(r"font-size:\s*(\d+)px", way)
    padding = re.search(r"padding:\s*(\d+)px", way)
    assert size and int(size.group(1)) >= 20 and padding and int(padding.group(1)) >= 22


def test_a_tile_links_to_the_tests_configuration_and_its_execution():
    script = script_of(read(PAGE))
    assert "data.engine_workspace" in script and "it.engine_name" in script
    assert re.search(r"ENGINE\s*\+\s*'/projects/'\s*\+\s*enc\(data\.engine_workspace\)\s*\+\s*'/plugins/'\s*\+\s*"
                     r"enc\(it\.engine_name\)", script), "C does not open the test's configuration"
    assert re.search(r"'/plugins/evaluation\?project='\s*\+\s*enc\(pid\)\s*\+\s*'&plugin='\s*\+\s*"
                     r"enc\(it\.engine_name\)", script), "E does not open the execution page on that test"
    for label in ("'C'", "'E'"):
        assert label in script, label


def test_a_tile_counts_the_runs_of_the_version_shown():
    script = script_of(read(PAGE))
    for field in ("runs.executed", "runs.failed", "runs.running"):
        assert field in script, field
    for word in ("executed", "failed", "running"):
        assert "'" + word + "'" in script or word + "'" in script, word
    # only installed tests get a tile: a removed one (kept for its links) has no runs
    assert re.search(r"filter\(function \(it\) \{\s*return it\.runs", script)


def test_a_disabled_test_has_no_e_since_the_execution_page_lists_only_enabled_ones():
    script = script_of(read(PAGE))
    body = re.search(r"function renderTiles\(\) \{(.*?)\n  \}", script, re.S).group(1)
    assert re.search(r"if \(it\.stale !== 'disabled'\)\s*\{?\s*tile\.appendChild\(tileLink\('E'", body), \
        "E is offered for a disabled test"
    assert "'Disabled in the engine'" in body


# ── step 4 control tiles (2026-10-03) ───────────────────────────────────────

def test_the_control_tiles_are_a_column_under_address_controls():
    markup = markup_of(read(PAGE))
    assert re.search(r'<div class="way-col">\s*<a\b[^>]*id="address-controls".*?</a>\s*'
                     r'<div class="tiles" id="control-tiles"', markup, re.S), "no tiles under Address controls"


def test_a_control_tile_shows_version_score_and_completion():
    script = script_of(read(PAGE))
    body = re.search(r"function renderControlTiles\(\) \{(.*?)\n  \}", script, re.S)
    assert body, "no renderControlTiles"
    body = body.group(1)
    for field in ("sub.version", "sub.readiness", "sub.answered", "it.questions"):
        assert field in body, field
    assert "'v' + sub.version" in body
    assert re.search(r"Math\.round\(100 \* sub\.answered / it\.questions\)", body), "completion is not answered / questions"
    assert "'Not answered yet'" in body
    # only installed checklists get a tile: a deleted one (kept for its links) has no questions
    assert re.search(r"filter\(function \(it\) \{\s*return it\.questions !== null", body)


def test_a_control_tile_opens_its_answers_or_the_checklist():
    body = re.search(r"function renderControlTiles\(\) \{(.*?)\n  \}", script_of(read(PAGE)), re.S).group(1)
    assert re.search(r"CONTROLS \+ '/p/' \+ enc\(pid\) \+ '/submissions/' \+ enc\(sub\.id\)", body)
    assert re.search(r"CONTROLS \+ '/p/' \+ enc\(pid\) \+ '/checklists/' \+ enc\(it\.key\) \+ '/fill'", body)
    assert "renderControlTiles();" in script_of(read(PAGE))


# ── step 4 third button (2026-10-03): the project's dashboard ───────────────

def test_a_third_big_button_opens_the_projects_tiles():
    """Plugin dashboards 2026-10-04 (T6.5): one tile per plugin, synced by the platform before it opens them."""
    html = read(PAGE)
    markup, script = markup_of(html), script_of(html)
    assert re.search(r'<div class="way-col">\s*<a class="way" id="visualise" href="[^"]+">Visualisation</a>', markup)
    assert "$('visualise').href = '/api/projects/' + enc(slug) + '/dashboards/open';" in script
    assert "8188/superset/dashboard/aisc-" not in script
    assert len(re.findall(r'<a class="way" ', markup)) == 3


# ── results navigation (2026-10-03, docs/superpowers/results-nav-2026-10-03/01-specs.md R3.1, R3.2) ──

def _target_tiles_body():
    body = re.search(r"function renderTargetTiles\(\) \{(.*?)\n  \}", script_of(read(PAGE)), re.S)
    assert body, "no renderTargetTiles"
    return body.group(1)


def test_r3_1_the_target_tiles_are_a_column_under_visualisation():
    markup = markup_of(read(PAGE))
    assert re.search(r'<a class="way" id="visualise" href="[^"]+">Visualisation</a>\s*'
                     r'<div class="tiles" id="target-tiles"', markup), "no tiles under Visualisation"
    assert "renderTargetTiles();" in script_of(read(PAGE))


def test_r3_1_a_target_tile_shows_kind_label_tools_and_runs():
    body = _target_tiles_body()
    assert "t.kind === 'system'" in body and "'SYSTEM'" in body
    assert "t.component_kind" in body and "toUpperCase()" in body
    assert "plural(t.tools.length, 'tool')" in body and "plural(runs, 'run')" in body
    assert "' failed'" in body


def test_r3_1_a_target_without_runs_is_greyed_and_not_a_link():
    body = _target_tiles_body()
    assert "'No runs yet'" in body and "'Not in the latest card'" in body
    assert re.search(r"if \(!runs\)", body)


def test_r3_2_a_tile_opens_the_results_page_of_its_target():
    body = _target_tiles_body()
    assert re.search(r"'/results\.html\?project=' \+ enc\(slug\) \+ '&target=' \+ "
                     r"enc\(t\.key === null \? 'none' : t\.key\)", body)
    assert re.search(r"\(version \? '&version=' \+ enc\(version\) : ''\)", body)


def test_r3_1_an_old_platform_without_targets_draws_no_tiles():
    assert re.search(r"if \(!data\.targets\) return;", _target_tiles_body())


# ── the three columns use the whole page width (2026-10-03) ─────────────────

def test_the_three_columns_sit_side_by_side_across_the_whole_page():
    html = read(PAGE)
    css = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", style_of(html))   # the wide-screen rules
    assert re.search(r"(?<![\w.-])main\{[^}]*max-width:\s*none", css), "the page is still capped"
    ways = rule(css, ".ways")
    assert "display:grid" in ways.replace(" ", "") and "repeat(3,minmax(0,1fr))" in ways.replace(" ", "")
    assert "max-width" not in rule(css, ".way-col")
    narrow = re.search(r"@media \(max-width:820px\)\{(.*?)\n  \}", style_of(html), re.S).group(1)
    assert re.search(r"\.ways\{[^}]*grid-template-columns:\s*1fr", narrow), "no single column on a phone"


# ── the AI Assessment Sandbox (2026-10-03, 02-sandbox-specs.md S2) ──────────

def test_s2_1_the_page_is_the_ai_assessment_sandbox():
    html = read(PAGE)
    markup, script = markup_of(html), script_of(html)
    assert '<p class="subtitle">AI Assessment Sandbox</p>' in markup
    assert "Step 4" not in markup and "Collect evidence" not in markup
    assert "document.title = p.name + ' - AI Assessment Sandbox'" in script


def test_s2_2_a_reports_button_top_right_level_with_the_project_name():
    html = read(PAGE)
    markup, script = markup_of(html), script_of(html)
    assert re.search(r'<div class="title-row">\s*<h1 class="title" id="project-name">&hellip;</h1>\s*'
                     r'<a class="reports" id="reports" href="[^"]+">Reports</a>\s*</div>', markup)
    assert re.search(r"\$\('reports'\)\.href\s*=\s*'http://localhost/report-composer/p/'\s*\+\s*enc\(p\.pid\)", script)
    assert re.search(r"\.title-row\{[^}]*justify-content:\s*space-between", style_of(html))


# ── 2026-10-04: no link tables; Visualisation shows the targets with runs first ──

def test_s3_1_the_objective_link_tables_are_gone_from_the_page():
    """The links stay in the platform (the report composer reads them); the page no longer edits them."""
    html = read(PAGE)
    markup, script = markup_of(html), script_of(html)
    for gone in ('id="links"', 'id="grid"', 'id="save"', 'id="links-help"', "Link tests and controls"):
        assert gone not in markup, gone
    for gone in ("/evidence/links", "function table(", "function save(", "function edges(", "linkId(", "not covered"):
        assert gone not in script, gone
    assert "'/api/projects/' + enc(slug) + '/evidence'" in script      # the tiles still come from there


def test_s3_2_targets_with_runs_on_top_the_others_in_a_closed_collapsible():
    body = _target_tiles_body()
    assert re.search(r"var idle = el\('details', 'idle'\)", body)
    assert ".open" not in body and "setAttribute('open'" not in body      # closed until opened
    assert re.search(r"el\('summary', null, 'Not run yet \(' \+ off\.length \+ '\)'\)", body)
    # the ones with runs go in the column first, then the collapsible holds the rest
    assert body.index("on.forEach(") < body.index("off.forEach(") < body.index("box.appendChild(idle)")
    assert re.search(r"if \(off\.length\)", body)
    css = style_of(read(PAGE))
    assert rule(css, "details.idle summary")


def test_s3_3_one_test_tile_per_engine_plugin():
    """A package may ship several plugins (data-monitor: Data Drift and Data Anomaly): the tiles come from
    the platform's per-plugin list, and from the per-package one only when an older platform sends no other."""
    body = re.search(r"function renderTiles\(\) \{(.*?)\n  \}", script_of(read(PAGE)), re.S).group(1)
    assert "var tests = (data.plugins || data.tests || []).filter(function (it) { return it.runs; });" in body


def test_address_controls_comes_before_execute_tests():
    """2026-10-05: the columns read Address controls, Execute tests, Visualisation, left to right."""
    markup = markup_of(read(PAGE))
    order = [m.group(1) for m in re.finditer(r'<div class="way-col">\s*<a\b[^>]*id="([a-z-]+)"', markup)]
    assert order == ["address-controls", "execute-tests", "visualise"], order
