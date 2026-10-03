"""The results page (results navigation 2026-10-03, docs/superpowers/results-nav-2026-10-03/01-specs.md
R3.3 to R3.5): one target's tools, each opening the project dashboard with Target and Tool set.
Static checks of the page source, like test_evidence_page.py."""
import re

from conftest import ROOT

PAGE = ROOT / "homepage/results.html"
EVIDENCE = ROOT / "homepage/evidence.html"


def read(path):
    assert path.is_file(), f"missing feature: {path.relative_to(ROOT)} does not exist"
    return path.read_text()


def script_of(html):
    return "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S | re.I))


def markup_of(html):
    return re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)


def test_it_has_step_4s_look_and_one_inline_script():
    html, reference = read(PAGE), read(EVIDENCE)
    for var in re.findall(r"(--[a-z0-9-]+)\s*:", re.search(r":root\s*\{(.*?)\}", reference, re.S).group(1)):
        assert re.search(re.escape(var) + r"\s*:", html), var
    assert 'class="session"' in html and 'id="who"' in html
    scripts = re.findall(r"<script\b([^>]*)>", html, re.I)
    assert len(scripts) == 1 and "src" not in scripts[0].lower()
    assert re.search(r"<title>Results\b", html)


def test_it_reads_the_project_and_its_evidence_view():
    script = script_of(read(PAGE))
    assert "'/api/projects/' + enc(slug)" in script
    assert "'/api/projects/' + enc(slug) + '/evidence'" in script
    assert "params.get('target')" in script and "params.get('version')" in script


def test_r3_3_the_breadcrumb_leads_back_to_step_4():
    script = script_of(read(PAGE))
    assert re.search(r"'/evidence\.html\?project=' \+ enc\(slug\)", script)
    assert "'AI Assessment Sandbox · Visualisation'" in script and "'\\u2190 Sandbox'" in script


def test_r3_3_one_big_button_per_tool_with_counts_and_last_run():
    script = script_of(read(PAGE))
    for field in ("it.executed", "it.failed", "it.running", "it.last_run"):
        assert field in script, field
    assert "'Open charts →'" in script
    assert "'All tools on this target →'" in script


def test_r3_3_dates_are_written_dd_mm_yyyy():
    script = script_of(read(PAGE))
    assert re.search(r"function day\(iso\)", script)
    assert re.search(r"\[pad\(d\.getDate\(\)\), pad\(d\.getMonth\(\) \+ 1\), d\.getFullYear\(\)\]\.join\('\.'\)", script)


def test_r3_3_installed_tools_not_run_on_this_target_are_greyed():
    script = script_of(read(PAGE))
    assert "'Installed, not run on this target yet'" in script
    assert re.search(r"\(?data\.tests(?: \|\| \[\]\))?\.filter\(function \(it\) \{\s*return it\.runs", script)


def test_r3_3_an_unknown_target_says_so():
    assert "'No such target in this project.'" in script_of(read(PAGE))


def test_r1_4_r3_4_links_set_the_fixed_filters_with_rison_quoting():
    script = script_of(read(PAGE))
    assert "'NATIVE_FILTER-target'" in script and "'NATIVE_FILTER-tool'" in script
    assert re.search(r"replace\(/!/g, '!!'\)\.replace\(/'/g, \"!'\"\)", script), "rison quoting"
    assert re.search(r"'/superset/dashboard/aisc-' \+ pid\.replace\(/-/g, ''\) \+ '/\?native_filters='", script)
    assert "extraFormData:(filters:!((col:" in script and "filterState:(value:!(" in script


def test_r3_4_the_no_target_entry_filters_on_unassigned():
    assert re.search(r"target\.key === null \? 'unassigned' : target\.label", script_of(read(PAGE)))
