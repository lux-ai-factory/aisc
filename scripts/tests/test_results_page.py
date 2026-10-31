"""The results page: one target's tools, each opening the project dashboard with Target and Tool set.
What it shows is decided by the platform's evidence view (platform/tests/test_evidence.py: each target's
greyed tools and each tool's dashboard_url); these static checks hold the page to rendering that answer."""
import re

from conftest import ROOT

PAGE = ROOT / "homepage/results.html"


def read(path):
    assert path.is_file(), f"missing feature: {path.relative_to(ROOT)} does not exist"
    return path.read_text()


def script_of(html):
    return "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S | re.I))


def markup_of(html):
    return re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)


def test_it_has_step_4s_look_and_one_inline_script():
    html = read(PAGE)
    assert '<link rel="stylesheet" href="/assets/launcher.css"/>' in html
    assert 'class="session"' in html and 'id="who"' in html
    scripts = re.findall(r"<script\b([^>]*)>", html, re.I)
    assert scripts == [' src="/assets/page.js"', ""], scripts
    assert re.search(r"<title>Results\b", html)


def test_it_reads_the_project_and_its_evidence_view():
    script = script_of(read(PAGE))
    assert "aisc.call('/api/projects/' + enc(slug))" in script
    assert "aisc.call('/api/projects/' + enc(slug) + '/evidence'" in script
    assert "params.get('target')" in script and "params.get('version')" in script
    assert "fetch(" not in script and ".json()" not in script


def test_a_refused_evidence_read_says_the_platforms_reason():
    """A 404 for an unknown version or a 503 is the platform's own sentence, not "not answering"."""
    assert re.search(r"if \(!ev\.ok\) \{ show\('page-message', ev\.message\); return; \}", script_of(read(PAGE)))


def test_the_breadcrumb_leads_back_to_step_4():
    script = script_of(read(PAGE))
    assert re.search(r"'/evidence\.html\?project=' \+ enc\(slug\)", script)
    assert "'Collect evidence · Results'" in script and "'\\u2190 Collect evidence'" in script
    assert "Sandbox'" not in script


def test_one_big_button_per_tool_with_counts_and_last_run():
    script = script_of(read(PAGE))
    for field in ("it.executed", "it.failed", "it.running", "it.last_run"):
        assert field in script, field
    assert "'Open charts →'" in script
    assert r"'Every test\'s charts →'" in script          # each test has its own tile
    assert "it.executed + ' completed · '" in script and "' executed" not in script


def test_dates_are_written_dd_mm_yyyy():
    script = script_of(read(PAGE))
    assert re.search(r"function day\(iso\)", script)
    assert re.search(r"\[pad\(d\.getDate\(\)\), pad\(d\.getMonth\(\) \+ 1\), d\.getFullYear\(\)\]\.join\('\.'\)", script)


def test_installed_tools_not_run_on_this_target_are_the_platforms_greyed_list():
    """Which tools are greyed is the platform's (each target's `greyed`): the page only lists them."""
    script = script_of(read(PAGE))
    assert "'Installed, not run on it yet'" in script
    assert "(target.greyed || []).forEach(function (it) {" in script
    assert "data.plugins" not in script and "data.tests" not in script and "toolId" not in script


def test_an_unknown_target_says_so():
    assert "'No such system or component in this project.'" in script_of(read(PAGE))


def test_links_are_the_platforms():
    """A tool's link is its dashboard_url and "All tools" the view's dashboards_url: the platform builds both
    (dashboards/open syncs the tile and sets the Target and Version filters)."""
    script = script_of(read(PAGE))
    assert "a.href = it.dashboard_url;" in script and "all.href = data.dashboards_url;" in script
    assert "dashboards/open" not in script and "native_filters=" not in script and "pid" not in script


def test_greyed_tiles_lay_out_like_the_blue_ones():
    """The greyed tiles are divs, not links: the tile layout (name, runs, one per line) is on .tool, so they
    get it too, not only a.tool (else their text runs together on one line)."""
    css = re.search(r"<style>(.*?)</style>", read(PAGE), re.S).group(1)
    rule = re.search(r"(?m)^\s*([^{}\n]*)\{([^}]*flex-direction:column[^}]*)\}", css[css.index(".tools{"):])
    selectors = [s.strip() for s in rule.group(1).split(",")]
    assert ".tool" in selectors, selectors
    assert "padding:24px 26px" in rule.group(2)


def test_the_heading_and_the_crumb_name_what_was_tested():
    html = read(PAGE)
    markup, script = markup_of(html), script_of(html)
    assert "<span>Tests run on this component</span>" in markup and "TARGET" not in markup
    assert "el('b', null, 'Tested: ' + target.label + ' (' + kindOf(target) + ')')" in script
    assert "return 'unassigned';" in script and "'no target'" not in script
    assert "'No tests installed yet: pick them in step 3, Tests and checklists.'" in script
    assert "'No such project: ' + slug + '.'" in script


# ── what each tool's runs assessed, how they reached it, and which helper models they used ──

def test_each_tool_says_it_assessed_the_ai_card_target_and_through_which_connection():
    script = script_of(read(PAGE))
    assert "'AI card · ' + target.label" in script
    assert "' · reached through '" in script
    assert "c.protocol_name + ' (' + c.name + ')'" in script
    assert "it.connections" in script and "target.key !== null" in script     # "No target" runs name no target


def test_each_tool_lists_its_helper_models_or_nothing():
    script = script_of(read(PAGE))
    assert "'Helper models: '" in script
    assert "if (it.helpers && it.helpers.length)" in script
    assert "h.role.charAt(0).toUpperCase() + h.role.slice(1) + ' ' + h.model" in script


def test_local_runs_are_not_on_a_targets_page():
    # they are listed once, on step 4 (evidence.html): a target's page shows only the AI card's runs
    html = read(PAGE)
    assert 'id="local"' not in markup_of(html) and "Local, not part of the assessment record" not in html
    assert "local_runs" not in script_of(html)


def test_the_page_builds_its_nodes_without_markup_strings_or_inline_handlers():
    html = read(PAGE)
    assert "innerHTML" not in script_of(html) and "insertAdjacentHTML" not in script_of(html)
    assert not re.search(r"\son[a-z]+\s*=", markup_of(html))
