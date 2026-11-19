"""The Manage menu is the last item of the launcher header, at the right edge, after the session line."""
import re
from pathlib import Path

HOMEPAGE = Path(__file__).resolve().parents[2] / "homepage"


def _topbar(html):
    start = html.index('<div class="topbar">')
    return html[start:html.index("\n</div>", start)]


def test_the_manage_menu_is_the_last_item_of_the_header_after_the_session_line():
    for page in ("project.html", "index.html"):
        bar = _topbar((HOMEPAGE / page).read_text())
        assert bar.index('<span class="session"') < bar.index('<details class="menu"'), page
        assert bar.rstrip().endswith("</details>"), page


def test_the_session_line_alone_pushes_to_the_right():
    css = (HOMEPAGE / "assets" / "launcher.css").read_text()
    assert not re.search(r"\.menu ~ \.session", css)
    for page in ("project.html", "index.html"):
        html = (HOMEPAGE / page).read_text()
        assert re.search(r"\.session\{margin-left:auto", html), page
        assert re.search(r"\.menu\{position:relative; margin-left:24px", html), page
