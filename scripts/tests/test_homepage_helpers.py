"""Static checks of the Helper models page and its link in the project page's Manage menu.

Run from the repo root:

    uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_homepage_helpers.py
"""

import re

from conftest import ROOT

PAGE = ROOT / "homepage/helpers.html"
PROJECT_PAGE = ROOT / "homepage/project.html"


def read(path):
    assert path.is_file(), f"missing feature: {path.relative_to(ROOT)} does not exist"
    return path.read_text()


def test_manage_menu_links_helper_models():
    html = read(PROJECT_PAGE)
    assert 'id="helper-models"' in html
    assert ">Helper models</span>" in html
    group = html.index(">Helper models</span>")
    assert html.index(">Assessed system</span>") < group
    link = html.index('id="helper-models"')
    assert group < link < html.index('class="danger admin-only"')
    assert re.search(r'id="helper-models"[^>]*class="member-only"|class="member-only"[^>]*id="helper-models"', html)
    assert "'/helpers.html?project=' + encodeURIComponent(slug)" in html


def test_helpers_page_never_renders_a_key_field_value():
    html = read(PAGE)
    assert re.search(r"<input[^>]*type=\"password\"", html)
    # the key field is only ever cleared
    assignments = re.findall(r"getElementById\('f-key'\)\.value\s*=(?!=)\s*([^;]*);", html)
    assert assignments and all(a.strip() == "''" for a in assignments), assignments
    assert not re.search(r"\bf-key\b[^\n]*\.value\s*=\s*(?!'')", html.replace("value = ''", ""))
    # a key never appears on the right-hand side of an assignment
    for line in html.splitlines():
        rhs = line.split("=", 1)[1] if re.search(r"(?<![=!<>])=(?!=)", line) else ""
        assert "api_key" not in rhs, line
    assert "onclick=" not in html and "localStorage" not in html


def test_helpers_page_uses_no_browser_dialog():
    html = read(PAGE)
    assert not re.search(r"\b(?:window\.)?(?:prompt|alert|confirm)\(", html)


def test_helpers_page_has_the_words_and_the_form():
    html = read(PAGE)
    assert "Models a test uses as a tool" in html
    assert "leave empty to keep the stored key" in html
    for role in ("judge", "attacker", "grader", "embedder", "generator"):
        assert role in html
