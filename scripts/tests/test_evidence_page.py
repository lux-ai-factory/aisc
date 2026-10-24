"""The Collect evidence page (evidence.html), step 4. The project page's sandbox card opens it; it has the
three ways on (the engine, the controls app, the dashboard) with their tiles. Its tables linking tests and
controls to the control objectives are gone from the page (the platform keeps the links, the report
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


# ── the page ────────────────────────────────────────────────────────────────

def test_the_page_has_the_launchers_look_and_one_inline_script():
    html, reference = read(PAGE), read(PROJECT_PAGE)
    for var in re.findall(r"(--[a-z0-9-]+)\s*:", re.search(r":root\s*\{(.*?)\}", reference, re.S).group(1)):
        assert re.search(re.escape(var) + r"\s*:", html), var
    assert 'class="session"' in html and 'id="who"' in html
    scripts = re.findall(r"<script\b([^>]*)>", html, re.I)
    # one inline script, and the shared origins helper (no link names localhost)
    assert scripts == [' src="/assets/origins.js"', ""], scripts
    assert re.search(r"<title>Collect evidence\b", html)


def test_it_has_the_two_buttons_into_the_project():
    html = read(PAGE)
    markup, script = markup_of(html), script_of(html)
    for id_, label in (("execute-tests", "Run tests"), ("address-controls", "Answer checklists")):
        link = re.search(r'<a\b[^>]*id="' + id_ + r'"[^>]*>(.*?)</a>', markup, re.S)
        assert link and label in link.group(1), id_
    assert re.search(r"aiscLink\(\$\('execute-tests'\), 'engine', '/\?project='\s*\+\s*enc\(p\.pid\)\)", script)
    assert re.search(r"aiscLink\(\$\('address-controls'\), 'engine', '/controls/p/'\s*\+\s*enc\(p\.pid\)\)",
                     script)


# ── helpers for the CSS ──

def style_of(html):
    return "\n".join(re.findall(r"<style\b[^>]*>(.*?)</style>", html, re.S | re.I))


def rule(css, selector):
    m = re.search(r"(?:^|[}\s])" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"no CSS rule for {selector}"
    return m.group(1)


# ── step 4: two big buttons and nothing else ────────────────────────────────

def test_the_two_ways_on_are_big_buttons_with_nothing_else():
    html = read(PAGE)
    markup, css = markup_of(html), style_of(html)
    assert re.search(r'<a class="way" id="execute-tests" data-origin="[^"]+" data-path="[^"]+">Run tests</a>', markup)
    assert re.search(r'<a class="way" id="address-controls" data-origin="[^"]+" data-path="[^"]+">Answer checklists</a>', markup)
    assert "<small>" not in markup and "Run the tests in the execution engine" not in markup
    way = rule(css, "a.way")
    # big enough for the test tiles that sit under Execute tests
    assert re.search(r"font-size\s*:\s*(1[4-9]|2\d)px", way) and re.search(r"padding\s*:\s*(1[6-9]|[2-4]\d)px", way)


# ── one AI card version at a time ────────────────────────────────────────────

def test_the_page_names_its_card_version_and_offers_the_others():
    html = read(PAGE)
    markup, script = markup_of(html), script_of(html)
    assert re.search(r'<select class="version" id="version"', markup)
    assert "var all = data.versions || [];" in script and "all.forEach(" in script and "data.version" in script
    # the version asked for travels in the address and to the platform
    assert "params.get('version')" in script
    assert "'/api/projects/' + enc(slug) + '/evidence' + (version ? '?version=' + enc(version) : '')" in script


def test_hidden_means_hidden_whatever_an_elements_display():
    # a `button { display: ... }` rule otherwise beats the hidden attribute: Save showed on a
    # read-only version, and to a viewer
    css = style_of(read(PAGE))
    assert re.search(r"\[hidden\]\s*\{\s*display\s*:\s*none\s*!important", css)


# ── step 4 test tiles ───────────────────────────────────────────────────────

def test_the_tests_tiles_are_a_column_under_execute_tests():
    markup = markup_of(read(PAGE))
    column = re.search(r'<div class="way-col">\s*(<a\b[^>]*id="execute-tests".*?</a>)\s*'
                       r'<div class="tiles" id="test-tiles"', markup, re.S)
    assert column, "the tiles do not sit under Execute tests"
    assert re.search(r'<div class="way-col">\s*<a\b[^>]*id="address-controls"', markup)


def test_a_tile_links_to_the_tests_configuration_and_its_execution():
    script = script_of(read(PAGE))
    assert "data.engine_workspace" in script and "it.engine_name" in script
    assert re.search(r"ENGINE\s*\+\s*'/projects/'\s*\+\s*enc\(data\.engine_workspace\)\s*\+\s*'/plugins/'\s*\+\s*"
                     r"enc\(it\.engine_name\)", script), "C does not open the test's configuration"
    assert re.search(r"'/plugins/evaluation\?project='\s*\+\s*enc\(pid\)\s*\+\s*'&plugin='\s*\+\s*"
                     r"enc\(it\.engine_name\)", script), "E does not open the execution page on that test"
    for label in ("'Configure'", "'Run'"):
        assert label in script, label
    assert "'C'" not in script and "'E'" not in script


def test_a_tile_counts_the_runs_of_the_version_shown():
    script = script_of(read(PAGE))
    for field in ("runs.executed", "runs.failed", "runs.running"):
        assert field in script, field
    assert "' executed'" not in script
    for word in ("completed", "failed", "running"):
        assert "'" + word + "'" in script or word + "'" in script, word
    # only installed tests get a tile: a removed one (kept for its links) has no runs
    assert re.search(r"filter\(function \(it\) \{\s*return it\.runs", script)


def test_a_disabled_test_has_no_e_since_the_execution_page_lists_only_enabled_ones():
    script = script_of(read(PAGE))
    body = re.search(r"function renderTiles\(\) \{(.*?)\n  \}", script, re.S).group(1)
    assert re.search(r"if \(it\.stale !== 'disabled'\)\s*\{?\s*tile\.appendChild\(tileLink\('Run'", body), \
        "E is offered for a disabled test"
    assert "'Disabled'" in body and "engine'" not in body


# ── step 4 control tiles ────────────────────────────────────────────────────

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
    assert re.search(r"total = sub\.questions !== undefined \? sub\.questions : it\.questions;[\s\S]*Math\.round\(100 \* sub\.answered / total\)", body), "completion is not answered / questions"
    assert "'Not answered yet'" in body
    assert "' · answered ' +" in body and "coverage" not in body
    assert "'No checklists installed yet: pick them in step 3, Tests and checklists.'" in body
    # only installed checklists get a tile: a deleted one (kept for its links) has no questions
    assert re.search(r"filter\(function \(it\) \{\s*return it\.questions !== null", body)


def test_a_control_tile_opens_its_answers_or_the_checklist():
    body = re.search(r"function renderControlTiles\(\) \{(.*?)\n  \}", script_of(read(PAGE)), re.S).group(1)
    assert re.search(r"CONTROLS \+ '/p/' \+ enc\(pid\) \+ '/submissions/' \+ enc\(sub\.id\)", body)
    assert re.search(r"CONTROLS \+ '/p/' \+ enc\(pid\) \+ '/checklists/' \+ enc\(it\.key\) \+ '/fill'", body)
    assert "renderControlTiles();" in script_of(read(PAGE))


# ── step 4 third button: the project's dashboard ────────────────────────────

def test_a_third_big_button_opens_the_projects_tiles():
    """Plugin dashboards: one tile per plugin, synced by the platform before it opens them."""
    html = read(PAGE)
    markup, script = markup_of(html), script_of(html)
    assert re.search(r'<div class="way-col">\s*<a class="way" id="visualise" data-origin="[^"]+" data-path="[^"]+">Results</a>', markup)
    assert "$('visualise').href = '/api/projects/' + enc(slug) + '/dashboards/open';" in script
    assert "8188/superset/dashboard/aisc-" not in script
    assert len(re.findall(r'<a class="way" ', markup)) == 4


# ── results navigation ──────────────────────────────────────────────────────

def _target_tiles_body():
    body = re.search(r"function renderTargetTiles\(\) \{(.*?)\n  \}", script_of(read(PAGE)), re.S)
    assert body, "no renderTargetTiles"
    return body.group(1)


def test_the_target_tiles_are_a_column_under_visualisation():
    markup = markup_of(read(PAGE))
    assert re.search(r'<a class="way" id="visualise" data-origin="[^"]+" data-path="[^"]+">Results</a>\s*'
                     r'<div class="tiles" id="target-tiles"', markup), "no tiles under Results"
    assert "renderTargetTiles();" in script_of(read(PAGE))


def test_a_target_tile_shows_kind_label_tools_and_runs():
    body = _target_tiles_body()
    assert "t.kind === 'system'" in body and "'SYSTEM'" in body and "TARGET" not in body
    assert "t.component_kind" in body and "toUpperCase()" in body
    assert "plural(t.tools.length, 'test')" in body and "plural(runs, 'run')" in body
    assert "' failed'" in body


def test_a_target_without_runs_is_greyed_and_not_a_link():
    body = _target_tiles_body()
    assert "'No runs yet'" in body and "'Not in the latest AI card'" in body
    assert re.search(r"if \(!runs\)", body)


def test_a_tile_opens_the_results_page_of_its_target():
    body = _target_tiles_body()
    assert re.search(r"'/results\.html\?project=' \+ enc\(slug\) \+ '&target=' \+ "
                     r"enc\(t\.key === null \? 'none' : t\.key\)", body)
    assert re.search(r"\(version \? '&version=' \+ enc\(version\) : ''\)", body)


def test_an_old_platform_without_targets_draws_no_tiles():
    assert re.search(r"if \(!data\.targets\) return;", _target_tiles_body())


# ── the runs on a local model file, apart ───────────────────────────────────

def _local_body():
    m = re.search(r"function renderLocal\(\) \{(.*?)\n  \}", script_of(read(PAGE)), re.S)
    assert m, "no renderLocal"
    return m.group(1)


def test_local_runs_are_a_block_of_their_own_under_the_results_targets():
    markup = markup_of(read(PAGE))
    assert re.search(r'<div class="tiles" id="target-tiles"[^>]*></div>\s*'
                     r'<div class="local" id="local" hidden>\s*<h3>Local, not part of the assessment record</h3>',
                     markup), "no local block under the Results tiles"
    assert '<div class="tiles" id="local-runs"' in markup
    assert "renderLocal();" in script_of(read(PAGE))


def test_a_local_run_names_its_tool_file_hash_status_and_day():
    body = _local_body()
    assert "(data.local_runs || []).forEach" in body
    assert "r.label" in body and "r.assessed.file.name" in body and "r.status" in body and "day(r.created_at)" in body
    # a run that failed before reading its file has no hash yet
    assert "r.assessed.file.sha256 ? ' (sha256 ' + r.assessed.file.sha256.slice(0, 12)" in body


def test_the_local_block_shows_only_when_there_are_local_runs():
    body = _local_body()
    assert "box.textContent = '';" in body and "$('local').hidden = !box.children.length;" in body


def test_the_page_builds_its_nodes_without_markup_strings_or_inline_handlers():
    html = read(PAGE)
    assert "innerHTML" not in script_of(html) and "insertAdjacentHTML" not in script_of(html)
    assert not re.search(r"\son[a-z]+\s*=", markup_of(html))


# ── the four columns use the whole page width ───────────────────────────────

def test_the_four_columns_sit_side_by_side_across_the_whole_page():
    html = read(PAGE)
    css = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", style_of(html))   # the wide-screen rules
    assert re.search(r"(?<![\w.-])main\{[^}]*max-width:\s*none", css), "the page is still capped"
    ways = rule(css, ".ways")
    assert "display:grid" in ways.replace(" ", "") and "repeat(4,minmax(0,1fr))" in ways.replace(" ", "")
    assert "max-width" not in rule(css, ".way-col")
    narrow = re.search(r"@media \(max-width:820px\)\{(.*?)\n  \}", style_of(html), re.S).group(1)
    assert re.search(r"\.ways\{[^}]*grid-template-columns:\s*1fr", narrow), "no single column on a phone"


# ── the AI Assessment Sandbox ───────────────────────────────────────────────

def test_the_page_is_collect_evidence():
    html = read(PAGE)
    markup, script = markup_of(html), script_of(html)
    assert '<p class="subtitle">Collect evidence</p>' in markup
    assert "AI Assessment Sandbox</" not in markup.replace("<h1>AI Assessment Sandbox Configurator</h1>", "")
    assert "document.title = p.name + ' - Collect evidence'" in script


def test_report_is_a_fourth_big_button_with_its_column():
    """The report composer is the last way on, like the other three, no longer a small button by the title."""
    html = read(PAGE)
    markup, script = markup_of(html), script_of(html)
    assert re.search(r'<div class="way-col">\s*<a class="way" id="write-report" data-origin="engine" '
                     r'data-path="/report-composer/">Report</a>\s*<div class="tiles" id="report-tiles"', markup)
    assert re.search(r"aiscLink\(\$\('write-report'\), 'engine', '/report-composer/p/'\s*\+\s*enc\(p\.pid\)\)", script)
    assert 'id="reports"' not in markup and "a.reports" not in style_of(html)


def _report_tiles_body():
    body = re.search(r"function renderReportTiles\(\) \{(.*?)\n  \}", script_of(read(PAGE)), re.S)
    assert body, "no renderReportTiles"
    return body.group(1)


def test_the_report_column_counts_the_versions_reports_and_links_the_newest():
    body = _report_tiles_body()
    assert "api('/api/projects/' + enc(slug) + '/reports?version=' + enc(data.version.pid))" in body
    assert "plural(d.count, 'report') + ' generated'" in body
    assert "d.latest.layout_name" in body
    assert "ENGINE + '/report-composer' + d.latest.download" in body
    assert "renderReportTiles();" in script_of(read(PAGE))


def test_the_report_column_says_when_there_is_nothing_or_the_composer_is_down():
    body = _report_tiles_body()
    assert re.search(r"if \(!data\.version\)", body)
    assert "'No report generated for this version yet.'" in body
    assert "'The reports could not be read right now.'" in body


# ── Visualisation shows the targets with runs first ──

def test_targets_with_runs_on_top_the_others_in_a_closed_collapsible():
    body = _target_tiles_body()
    assert re.search(r"var idle = el\('details', 'idle'\)", body)
    assert ".open" not in body and "setAttribute('open'" not in body      # closed until opened
    assert re.search(r"el\('summary', null, 'Not run yet \(' \+ off\.length \+ '\)'\)", body)
    # the ones with runs go in the column first, then the collapsible holds the rest
    assert body.index("on.forEach(") < body.index("off.forEach(") < body.index("box.appendChild(idle)")
    assert re.search(r"if \(off\.length\)", body)
    css = style_of(read(PAGE))
    assert rule(css, "details.idle summary")


def test_one_test_tile_per_engine_plugin():
    """A package may ship several plugins (data-monitor: Data Drift and Data Anomaly): the tiles come from
    the platform's per-plugin list, and from the per-package one only when an older platform sends no other."""
    body = re.search(r"function renderTiles\(\) \{(.*?)\n  \}", script_of(read(PAGE)), re.S).group(1)
    assert "var tests = (data.plugins || data.tests || []).filter(function (it) { return it.runs; });" in body


def test_address_controls_comes_before_execute_tests():
    """The columns read Answer checklists, Run tests, Results, Report, left to right."""
    markup = markup_of(read(PAGE))
    order = [m.group(1) for m in re.finditer(r'<div class="way-col">\s*<a\b[^>]*id="([a-z-]+)"', markup)]
    assert order == ["address-controls", "execute-tests", "visualise", "write-report"], order


def test_the_empty_states_and_the_missing_project_use_the_step_names():
    script = script_of(read(PAGE))
    assert "'No tests installed yet: pick them in step 3, Tests and checklists.'" in script
    assert "the catalogue.'" not in script and "'No project with the handle" not in script
    assert "'No such project: ' + slug + '.'" in script


def test_no_em_dash_in_the_page():
    assert "\u2014" not in read(PAGE) and "&mdash;" not in read(PAGE)
