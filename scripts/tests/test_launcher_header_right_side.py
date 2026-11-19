"""The Manage menu and the session line sit together at the right edge of the launcher header."""
import re
from pathlib import Path

HOMEPAGE = Path(__file__).resolve().parents[2] / "homepage"


def test_the_session_line_follows_the_menu_without_its_own_push():
    css = (HOMEPAGE / "assets" / "launcher.css").read_text()
    assert re.search(r"\.topbar \.menu ~ \.session\s*\{[^}]*margin-left:\s*0", css)
    for page in ("project.html", "index.html"):
        html = (HOMEPAGE / page).read_text()
        assert '<details class="menu"' in html and '<span class="session"' in html
        assert html.index('<details class="menu"') < html.index('<span class="session"'), page
