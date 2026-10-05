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


def rule(selector):
    """The declarations of the first rule whose selector list is exactly `selector`."""
    m = re.search(r"(?:^|[}\s])" + re.escape(selector) + r"\s*\{([^}]*)\}", style())
    assert m, selector
    return m.group(1)


def px(decls, prop):
    m = re.search(r"(?:^|[;\s{])" + re.escape(prop) + r"\s*:\s*([\d.]+)px", decls)
    assert m, prop
    return float(m.group(1))


def test_s1_5_the_sandbox_card_is_centred():
    card = rule(".row.one .card")
    assert re.search(r"text-align\s*:\s*center", card)
    assert re.search(r"align-items\s*:\s*center", card)
    assert re.search(r"margin\s*:\s*0 auto", rule(".row.one .card p"))


def test_s1_6_the_arrows_are_thick():
    for sel in (".arrow::before", ".down::before"):
        assert re.search(r"border-(top|left)\s*:\s*3px solid", rule(sel)), sel
    assert px(rule(".arrow::after"), "border-left") >= 12
    assert px(rule(".down::after"), "border-top") >= 12
    assert re.search(r"stroke-width\s*:\s*2\.6", rule(".open svg"))


def test_s1_7_the_plan_block_is_compact():
    assert px(rule("#plan-block .card"), "padding") <= 24
    assert px(rule("#plan-block .card h2"), "margin") <= 18


def test_s1_8_the_steps_start_at_the_top_so_a_shorter_plan_block_lifts_the_sandbox():
    assert re.search(r"justify-content\s*:\s*flex-start", rule("main"))
