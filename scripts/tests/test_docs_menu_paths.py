"""Every "Manage > ..." path the README and the docs give names an entry of the project page's Manage menu, and
a path into Connectivity names one of its tabs: a reader who follows the docs finds the entry they name."""
import html
import re

from conftest import ROOT

DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]


def _menu_names() -> list[str]:
    page = (ROOT / "homepage/project.html").read_text()
    menu = page.split('id="delete-open"', 1)[0].rsplit("<details", 1)[1]
    names = re.findall(r'<(?:a|span|button)\b[^>]*>([^<]+)</(?:a|span|button)>', menu)
    return [html.unescape(n).strip() for n in names if n.strip()]


def _connectivity_tabs() -> list[str]:
    page = (ROOT / "homepage/connectivity.html").read_text()
    return re.findall(r'role="tab"[^>]*>\s*<span class="k">[^<]*</span><span class="n">([^<]+)</span>', page)


def _paths():
    for doc in DOCS:
        text = re.sub(r"\s+", " ", doc.read_text().replace("**", ""))
        for found in re.finditer(r"Manage > (.{0,80})", text):
            yield doc.relative_to(ROOT), found.group(1)


def test_every_manage_path_in_the_docs_names_an_entry_of_the_menu():
    names, tabs = _menu_names(), _connectivity_tabs()
    assert "Connectivity" in names and "Test tools" in tabs
    wrong = []
    for doc, rest in _paths():
        entry = next((n for n in names if rest.startswith(n)), None)
        if entry is None:
            wrong.append(f"{doc}: Manage > {rest}")
        elif entry == "Connectivity" and rest.startswith("Connectivity > "):
            if not any(rest[len("Connectivity > "):].startswith(t) for t in tabs):
                wrong.append(f"{doc}: Manage > {rest}")
    assert wrong == []
