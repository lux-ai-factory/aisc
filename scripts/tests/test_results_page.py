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
    assert r"'Every tool\'s tile →'" in script          # each tool has its own tile since 2026-10-04


def test_r3_3_dates_are_written_dd_mm_yyyy():
    script = script_of(read(PAGE))
    assert re.search(r"function day\(iso\)", script)
    assert re.search(r"\[pad\(d\.getDate\(\)\), pad\(d\.getMonth\(\) \+ 1\), d\.getFullYear\(\)\]\.join\('\.'\)", script)


def test_r3_3_installed_tools_not_run_on_this_target_are_greyed():
    script = script_of(read(PAGE))
    assert "'Installed, not run on this target yet'" in script
    assert re.search(r"\(data\.plugins \|\| data\.tests \|\| \[\]\)\.filter\(function \(it\) \{\s*return it\.runs", script)


def test_r3_3_each_engine_plugin_counts_on_its_own_even_when_two_share_a_package():
    """data-monitor ships Data Drift and Data Anomaly (2026-10-04): one that ran on the target must not hide
    the other, so a tool is matched by its package and its label, as the target's tools are listed."""
    script = script_of(read(PAGE))
    assert "function toolId(it) { return it.key + '|' + it.label; }" in script
    assert "target.tools.forEach(function (it) { ran[toolId(it)] = true; });" in script
    assert "return it.runs && !ran[toolId(it)];" in script


def test_r3_3_an_unknown_target_says_so():
    assert "'No such target in this project.'" in script_of(read(PAGE))


def test_r1_4_r3_4_links_go_through_the_platform_to_the_tools_tile():
    """Plugin dashboards 2026-10-04 (T6.6): a tool's link opens its own tile, synced first, with the Target
    filter set by the platform (dashboards/open); "All tools" opens the project's tiles."""
    script = script_of(read(PAGE))
    assert ("return '/api/projects/' + enc(slug) + '/dashboards/open' + (tool ? '?plugin=' + enc(tool.label) + "
            "'&target=' + enc(target.key === null ? 'unassigned' : target.label) : '');") in script
    assert "aisc-' + pid" not in script and "native_filters=" not in script   # the platform builds those now


def test_r3_4_the_no_target_entry_filters_on_unassigned():
    assert re.search(r"target\.key === null \? 'unassigned' : target\.label", script_of(read(PAGE)))


def test_r3_3_greyed_tiles_lay_out_like_the_blue_ones():
    """The greyed tiles are divs, not links: the tile layout (name, runs, one per line) is on .tool, so they
    get it too, not only a.tool (2026-10-05: their text ran together on one line)."""
    css = re.search(r"<style>(.*?)</style>", read(PAGE), re.S).group(1)
    rule = re.search(r"(?m)^\s*([^{}\n]*)\{([^}]*flex-direction:column[^}]*)\}", css[css.index(".tools{"):])
    selectors = [s.strip() for s in rule.group(1).split(",")]
    assert ".tool" in selectors, selectors
    assert "padding:24px 26px" in rule.group(2)
