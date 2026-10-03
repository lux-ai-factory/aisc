"""The project page as two blocks (2026-10-03, docs/superpowers/results-nav-2026-10-03/02-sandbox-specs.md):
"Plan the assessment" with its three steps, an arrow down, then the AI Assessment Sandbox."""
import re

from conftest import ROOT

PAGE = ROOT / "homepage/project.html"


def html():
    return PAGE.read_text()


def markup():
    return re.sub(r"<script\b[^>]*>.*?</script>", "", html(), flags=re.S | re.I)


def style():
    return "\n".join(re.findall(r"<style\b[^>]*>(.*?)</style>", html(), re.S | re.I))


def test_s1_1_the_plan_block_holds_the_three_planning_steps_in_order():
    block = re.search(r'<section class="block" id="plan-block">(.*?)</section>', markup(), re.S)
    assert block, "no plan block"
    body = block.group(1)
    assert re.search(r'<h2 class="block-title">Plan the assessment</h2>', body)
    ids = re.findall(r'<a class="card" id="([a-z-]+)"', body)
    assert ids == ["qualification-card", "control-objectives-card", "catalogue-card"]
    assert body.count('<div class="arrow" aria-hidden="true"></div>') == 2


def test_s1_2_no_step_numbers():
    assert 'class="n"' not in markup()
    assert ".card .n" not in style()


def test_s1_3_an_arrow_down_then_the_sandbox_card():
    m = re.search(r'</section>\s*<div class="down" aria-hidden="true"></div>\s*'
                  r'<section class="block sandbox">\s*<div class="row one">\s*'
                  r'<a class="card" id="sandbox-card"[^>]*>(.*?)</a>', markup(), re.S)
    assert m, "no arrow down to the sandbox card"
    assert "<h2>AI Assessment Sandbox</h2>" in m.group(1)
    assert re.search(r"getElementById\('sandbox-card'\)\.href\s*=\s*'/evidence\.html\?project='\s*\+\s*"
                     r"encodeURIComponent\(slug\)", html())


def test_s1_4_steps_5_and_6_are_gone():
    page = markup()
    for gone in ('id="report-composer-card"', "Analyse results", "Compose the report", 'href="http://localhost:8188/"',
                 'id="evidence-card"'):
        assert gone not in page, gone
    assert "'report-composer-card'" not in html()


def test_s1_4_the_catalogue_still_learns_where_the_controls_app_is():
    assert re.search(r'<a class="card" id="sandbox-card"[^>]*data-controls="http://localhost/controls"', markup())
    assert re.search(r"getElementById\('sandbox-card'\)[\s\S]{0,200}dataset\.controls", html())
