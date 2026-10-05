"""The catalogue choice on the launcher (local-catalogue 2026-10-03, docs/superpowers/local-catalogue-2026-10-03/
01-specs.md L1.1, L1.2): the plan block's catalogue card asks the platform for the project's mode; no mode
opens homepage/catalogue.html (the choice), a private copy the catalogue's own pages served by this stack under
/private-catalogue/, public the hosted catalogue as before."""
import re

from conftest import ROOT

PROJECT = ROOT / "homepage/project.html"
PAGE = ROOT / "homepage/catalogue.html"
EVIDENCE = ROOT / "homepage/evidence.html"


def read(path):
    assert path.is_file(), f"missing feature: {path.relative_to(ROOT)} does not exist"
    return path.read_text()


def script_of(html):
    return "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S | re.I))


def markup_of(html):
    return re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)


def _card_handler():
    script = script_of(read(PROJECT))
    m = re.search(r"var card = document\.getElementById\('catalogue-card'\);(.*?)\n  \}\)\(\);", script, re.S)
    assert m, "no catalogue card handler"
    return m.group(1)


def test_l1_1_the_card_asks_the_platform_for_the_projects_mode():
    handler = _card_handler()
    assert "'/api/projects/' + encodeURIComponent(slug) + '/catalogue'" in handler
    assert "e.preventDefault();" in handler


def test_l1_1_no_mode_opens_the_choice_page():
    handler = _card_handler()
    assert re.search(r"if \(d && d\.mode === null\)", handler)
    assert "'/catalogue.html?project=' + encodeURIComponent(slug)" in handler


def test_l1_2_either_catalogue_opens_the_catalogues_own_pages_here_with_the_hand_over():
    """Public or private, the stack's pages (plan 2026-10-04 D1): a public project's read the public catalogue
    live. The #env= hand-over tells them where the engine and the controls app are, so Install reaches them."""
    handler = _card_handler()
    assert "var pages = '/project-catalogue/catalogue?project=' + encodeURIComponent(slug);" in handler
    assert re.search(r"function open\(address\)", handler)
    assert "address + '#env=' + btoa(JSON.stringify(payload))" in handler
    assert re.search(r"\.then\(function \(d\) \{\s*if \(d && d\.mode === null\)", handler)
    assert handler.count("open(pages)") == 2, "a chosen catalogue and no answer both open the pages"
    assert re.search(r"\.catch\(function \(\) \{\s*open\(pages\);", handler)


def test_l1_1_the_online_site_is_no_longer_opened_from_a_project():
    html = read(PROJECT)
    assert "hosted()" not in _card_handler() and "sandboxconfigurator" not in html
    assert '<a class="card" id="catalogue-card" data-engine="http://localhost/" href="/catalogue.html">' in html


def test_the_page_has_the_launchers_look_and_one_inline_script():
    html, reference = read(PAGE), read(EVIDENCE)
    for var in re.findall(r"(--[a-z0-9-]+)\s*:", re.search(r":root\s*\{(.*?)\}", reference, re.S).group(1)):
        assert re.search(re.escape(var) + r"\s*:", html), var
    scripts = re.findall(r"<script\b([^>]*)>", html, re.I)
    assert len(scripts) == 1 and "src" not in scripts[0].lower()
    assert re.search(r"<title>Catalogue\b", html)


def test_the_choice_explains_both_and_that_it_is_final():
    markup = markup_of(read(PAGE))
    choice = re.search(r'<section id="choice"[^>]*>(.*?)</section>', markup, re.S)
    assert choice, "no choice section"
    body = choice.group(1)
    assert re.search(r'<button[^>]*data-mode="public"', body) and re.search(r'<button[^>]*data-mode="private"', body)
    for words in ("Public catalogue", "Private catalogue", "cannot be changed later", "control objectives",
                  "local plugins"):
        assert words in body, words


def test_choosing_posts_the_mode_and_says_why_it_failed():
    script = script_of(read(PAGE))
    assert "'/api/projects/' + enc(slug) + '/catalogue'" in script
    assert "method: 'POST'" in script and "{mode: mode}" in script
    for status in ("409", "503"):
        assert status in script, status


def test_once_chosen_the_page_goes_on_to_the_chosen_catalogue():
    """The private copy's state and Update from public are in the catalogue's own pages now, so this page
    only makes the choice; once one is made, the project page opens the chosen catalogue."""
    html = read(PAGE)
    markup, script = markup_of(html), script_of(html)
    assert 'id="private"' not in markup and 'id="update"' not in markup
    assert re.search(r"if \(d\.mode !== null\) \{ location\.href = '/p/' \+ enc\(slug\) \+ '\?open=catalogue'", script)


def test_a_choice_goes_on_to_the_chosen_catalogue_through_the_project_page():
    """After choosing, the project page opens the catalogue's pages itself (it builds the hand-over)."""
    assert "'/p/' + enc(slug) + '?open=catalogue'" in script_of(read(PAGE))
    assert re.search(r"\.get\('open'\) === 'catalogue'\) card\.click\(\)", script_of(read(PROJECT)))
