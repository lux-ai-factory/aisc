"""After "sign out" the browser goes back to / and must ask the server for it, so the gateway can send it to the
sign-in page. A launcher page served with no Cache-Control may be reused from the browser's cache: the old
page then calls the platform signed out and says the platform cannot be reached."""
import re

import pytest

from conftest import ROOT


def _handle(header):
    text = (ROOT / "Caddyfile").read_text()
    start = text.index("{$CADDY_DOMAIN}:{$HOMEPAGE_PORT} {")
    site = text[start:text.index("\n}\n", start)]
    m = re.search(r"\n    " + re.escape(header) + r" \{\n(.*?)\n    \}\n", site, re.S)
    assert m, header
    return m.group(1)


@pytest.mark.parametrize("header", ["handle", "handle /p/*"])
def test_the_launcher_pages_are_asked_for_again_every_time(header):
    lines = [line.strip() for line in _handle(header).splitlines()]
    assert "header Cache-Control no-cache" in lines, header
