"""The left menu of qualification, control objectives and controls is fixed against the left edge, under the
header, from there to the bottom of the window: scrolling the page never moves it, and it adds no height to the
page (a sticky menu as tall as the window made short pages scroll, and then scrolled away behind the header).
Only on a narrow window (760px or less) does it go above the content, as a plain block."""
import re

import pytest

from conftest import ROOT

MENUS = {
    "qualification": (ROOT / "apps/qualification/src/app/globals.css", ".qf-sidemenu"),
    "control objectives": (ROOT / "apps/control-objectives/src/aisc_control_objectives/templates/_base.html.j2",
                           ".co-sidemenu"),
    "controls": (ROOT / "apps/controls/src/app/globals.css", ".cl-sidemenu"),
}


def rule(css: str, selector: str) -> str:
    """The declarations of the first rule for exactly this selector."""
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"no rule for {selector}"
    return re.sub(r"\s+", " ", m.group(1))


@pytest.mark.parametrize("app", MENUS)
def test_the_menu_is_fixed_to_the_left_edge_under_the_header(app):
    path, selector = MENUS[app]
    css = path.read_text()
    decl = rule(css, selector)
    assert "position: fixed" in decl, decl
    assert re.search(r"left: 0\b", decl), decl
    assert "top: var(--site-header-h)" in decl, decl
    assert re.search(r"bottom: 0\b", decl), decl
    assert "100vh" not in decl, "a menu as tall as the window makes short pages scroll"


def media_blocks(css: str):
    """(max-width, the block's text) of every @media (max-width: Npx) block, its braces matched."""
    for m in re.finditer(r"@media \(max-width: (\d+)px\)\s*\{", css):
        depth, i = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        yield m.group(1), css[m.end():i - 1]


@pytest.mark.parametrize("app", MENUS)
def test_only_a_narrow_window_puts_the_menu_above_the_content(app):
    path, selector = MENUS[app]
    narrow = [width for width, block in media_blocks(path.read_text())
              if re.search(re.escape(selector) + r"\s*\{", block)]
    assert narrow == ["760"], narrow
