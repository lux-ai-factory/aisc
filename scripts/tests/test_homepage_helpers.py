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
    assert re.search(r"<input[^>]*type=\"password\"|\.type = 'password'", html)
    assert not re.search(r"keyInput\.value\s*=\s*[^'\"\s]", html)      # only ever cleared
    assert not re.search(r"api_key\s*[:=]\s*(?:d|row|h)\.", html)
    assert "onclick=" not in html and "localStorage" not in html


def test_helpers_page_has_the_words_and_the_form():
    html = read(PAGE)
    assert "Models a test uses as a tool" in html
    assert "leave empty to keep the stored key" in html
    for role in ("judge", "attacker", "grader", "embedder", "generator"):
        assert role in html
