"""No launcher page leads to "No project with the handle ." (reported 2026-10-06, coming back from the engine).

The project page's step-1 and step-4 cards started as /catalogue.html and /evidence.html with no project, and
got their ?project= only once the project had loaded: clicked before that, the page opened with an empty
project, and its Back link became '/p/' + '' (the project page with an empty handle). Now the cards have no
address until the project is known, and a page opened without a project goes to the launcher's list of
projects instead of building links from an empty one. Static checks of the page sources."""
import re

import pytest

from conftest import ROOT

PAGES = ["evidence", "results", "catalogue", "connections", "llm", "logs"]


def script_of(name):
    html = (ROOT / f"homepage/{name}.html").read_text()
    return "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S | re.I))


@pytest.mark.parametrize("name", PAGES)
def test_a_page_opened_without_a_project_goes_to_the_launcher(name):
    script = script_of(name)
    m = re.search(r"var slug = [^;]*get\('project'\)[^;]*;", script)
    assert m, f"{name}: where it reads ?project="
    rest = script[m.end():m.end() + 300]
    assert re.search(r"if \(!slug\) \{ location\.replace\('/'\); throw new Error\('no project'\); \}", rest), \
        f"{name}: no redirect for an empty project right after reading it"


def test_the_project_page_without_a_handle_goes_to_the_launcher():
    script = script_of("project")
    m = re.search(r"var slug = decodeURIComponent\(window\.location\.pathname[^;]*;", script)
    assert m and re.search(r"if \(!slug\) \{ location\.replace\('/'\); throw new Error\('no project'\); \}",
                           script[m.end():m.end() + 400])


def test_the_step_4_card_is_linked_with_its_project_before_anything_loads():
    """The project page knows its handle from its own address; the card no longer starts as a bare
    /evidence.html that a click during loading would open. (The catalogue card's clicks are all taken by
    its handler, which builds the address from the handle.)"""
    html = (ROOT / "homepage/project.html").read_text()
    tag = re.search(r'<a\b[^>]*id="sandbox-card"[^>]*>', html).group(0)
    assert " href=" not in tag, tag
    script = script_of("project")
    linked = script.index("getElementById('sandbox-card').href = '/evidence.html?project=' + encodeURIComponent(slug)")
    assert linked < script.index("fetch('/api/projects/' + encodeURIComponent(slug)")
