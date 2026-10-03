"""The catalogue choice on the launcher (local-catalogue 2026-10-03, docs/superpowers/local-catalogue-2026-10-03/
01-specs.md L1.1): the plan block's catalogue card asks the platform for the project's mode; no mode or a
private copy opens homepage/catalogue.html, public opens the hosted catalogue as before."""
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


def test_l1_1_no_mode_or_private_opens_the_choice_page():
    handler = _card_handler()
    assert re.search(r"if \(d && d\.mode !== 'public'\)", handler)
    assert "'/catalogue.html?project=' + encodeURIComponent(slug)" in handler


def test_l1_1_public_or_no_answer_opens_the_hosted_catalogue_as_before():
    handler = _card_handler()
    assert "'/#env=' + btoa(JSON.stringify(payload))" in handler
    assert re.search(r"\.catch\(function \(\) \{\s*hosted\(\);", handler), "no answer must fall back to the hosted one"


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


def test_the_private_copy_shows_its_state_and_admins_update_it():
    html = read(PAGE)
    markup, script = markup_of(html), script_of(html)
    assert re.search(r'<section id="private"[^>]*hidden', markup)
    assert re.search(r'<button[^>]*id="update"[^>]*hidden[^>]*>Update from public</button>', markup)
    assert "'/api/projects/' + enc(slug) + '/catalogue/update'" in script
    assert "d.can_update" in script
    for field in ("added", "updated", "unchanged", "removed", "local_kept"):
        assert "r." + field in script or "d." + field in script, field


def test_a_public_choice_goes_on_to_the_hosted_catalogue():
    """After choosing public, the project page opens the hosted catalogue itself (it builds the hand-over)."""
    assert "'/p/' + enc(slug) + '?open=catalogue'" in script_of(read(PAGE))
    assert re.search(r"\.get\('open'\) === 'catalogue'\) card\.click\(\)", script_of(read(PROJECT)))
