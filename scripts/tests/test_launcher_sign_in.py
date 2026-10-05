"""Signing in from a project's page must bring the person back to that page. Caddy runs `rewrite`
before `route` (protect), so with the rewrite outside protect's route the sign-in records /project.html
and the person lands on a page with no project."""
import re

from conftest import ROOT


def _handle(header):
    text = (ROOT / "Caddyfile").read_text()
    start = text.index("{$CADDY_DOMAIN}:{$HOMEPAGE_PORT} {")
    site = text[start:text.index("\n}\n", start)]
    m = re.search(re.escape(header) + r" \{\n(.*?)\n    \}\n", site, re.S)
    assert m, header
    return m.group(1)


def test_a_projects_page_signs_in_before_it_is_rewritten():
    body = _handle("handle /p/*")
    route = re.search(r"route \{\n(.*?)\n      \}", body, re.S)
    assert route, "no route: Caddy would rewrite before sign-in"
    steps = [l.strip() for l in route.group(1).splitlines() if l.strip() and not l.strip().startswith("#")]
    assert steps.index("import protect launcher") < steps.index("rewrite * /project.html"), steps
