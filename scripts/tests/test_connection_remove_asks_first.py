"""Manage > Connectivity > the assessed system's connections (homepage/connections.html): Remove on a connection
unlinks its target and ends its agent and tool uses, and only a key typed again brings it back. So Remove asks
first, naming what the connection reaches; one click alone sends nothing. Static checks of the page source, like
test_connections_page.py."""
import re

from conftest import ROOT

PAGE = ROOT / "homepage/connections.html"


def script_of(html):
    return "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S | re.I))


def remove_handlers(script):
    """The body of each click handler given to a Remove button: button('danger', 'Remove', function () {...})."""
    bodies = []
    for m in re.finditer(r"button\(\s*'danger'\s*,\s*'Remove'\s*,\s*function\s*\(\)\s*\{", script):
        depth, i = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(script[i], 0)
            i += 1
        bodies.append(script[m.end():i - 1])
    return bodies


def test_the_page_has_its_two_remove_buttons():
    assert len(remove_handlers(script_of(PAGE.read_text()))) == 2


def test_remove_never_deletes_a_connection_on_one_click():
    for body in remove_handlers(script_of(PAGE.read_text())):
        direct = re.search(r"write\(\s*'DELETE'", body)
        asks = re.search(r"\bconfirm\(", body)
        assert not direct or (asks and asks.start() < direct.start()), (
            f"Remove sends the delete without asking first: {body.strip()}")
