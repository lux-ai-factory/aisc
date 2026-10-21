"""The project page as two blocks:
"Plan the assessment" with its three steps, an arrow down, then step 4, Collect evidence."""
import re

from conftest import ROOT

PAGE = ROOT / "homepage/project.html"


def html():
    return PAGE.read_text()


def markup():
    return re.sub(r"<script\b[^>]*>.*?</script>", "", html(), flags=re.S | re.I)


def style():
    return "\n".join(re.findall(r"<style\b[^>]*>(.*?)</style>", html(), re.S | re.I))


def test_the_plan_block_holds_the_three_planning_steps_in_order():
    block = re.search(r'<section class="block" id="plan-block">(.*?)</section>', markup(), re.S)
    assert block, "no plan block"
    body = block.group(1)
    assert re.search(r'<h2 class="block-title">Plan the assessment</h2>', body)
    ids = re.findall(r'<a class="card" id="([a-z-]+)"', body)
    assert ids == ["qualification-card", "control-objectives-card", "catalogue-card"]
    assert body.count('<div class="arrow" aria-hidden="true"></div>') == 2


def test_no_step_numbers():
    assert 'class="n"' not in markup()
    assert ".card .n" not in style()


def test_an_arrow_down_then_the_sandbox_card():
    m = re.search(r'</section>\s*<div class="down" aria-hidden="true"></div>\s*'
                  r'<section class="block sandbox">\s*<div class="row one">\s*'
                  r'<a class="card" id="sandbox-card"[^>]*>(.*?)</a>', markup(), re.S)
    assert m, "no arrow down to the sandbox card"
    assert "<h2>4. Collect evidence</h2>" in m.group(1)
    assert "<p>Answer the checklists, run the tests, see the results and compose the report, in one place.</p>" in m.group(1)
    assert re.search(r"getElementById\('sandbox-card'\)\.href\s*=\s*'/evidence\.html\?project='\s*\+\s*"
                     r"encodeURIComponent\(slug\)", html())


def test_the_catalogue_still_learns_where_the_controls_app_is():
    # under the engine's site, wherever the install puts it (assets/origins.js)
    assert re.search(r"function controlsBase\(\) \{\s*return window\.aiscOrigin\('engine'\) \+ '/controls';", html())


def rule(selector):
    """The declarations of the first rule whose selector list is exactly `selector`."""
    m = re.search(r"(?:^|[}\s])" + re.escape(selector) + r"\s*\{([^}]*)\}", style())
    assert m, selector
    return m.group(1)


def test_the_sandbox_card_is_centred():
    card = rule(".row.one .card")
    assert re.search(r"text-align\s*:\s*center", card)
    assert re.search(r"align-items\s*:\s*center", card)
    assert re.search(r"margin\s*:\s*0 auto", rule(".row.one .card p"))


def test_the_steps_start_at_the_top_so_a_shorter_plan_block_lifts_the_sandbox():
    assert re.search(r"justify-content\s*:\s*flex-start", rule("main"))


def test_the_four_cards_carry_the_one_numbering_and_its_names():
    body = markup()
    for card, title, text in (
            ("qualification-card", "1. Qualify the AI system",
             "Describe the system and its components in its AI card, and find its AI Act risk class."),
            ("control-objectives-card", "2. Set control objectives",
             "Rate the system's risks and link them to the control objectives it must meet."),
            ("catalogue-card", "3. Choose tests and checklists", "Pick tests and checklists, and install them in one click.")):
        m = re.search(r'<a class="card" id="' + card + r'"[^>]*>(.*?)</a>', body, re.S)
        assert m and "<h2>" + title + "</h2>" in m.group(1) and "<p>" + text + "</p>" in m.group(1), card
    assert "system card" not in body and "Identify tests" not in body


def test_no_em_dash_and_no_handle_in_what_the_page_shows():
    assert "\u2014" not in html() and "&mdash;" not in html()
    assert "'No such project: ' + slug + '.'" in html() and "'No project with the handle '" not in html()
