"""An owner manages the project's members in the launcher: a page under Manage lists them, adds someone, changes a
role and removes someone, through the platform's member routes, and the project menu links it for owners and
admins only. Static checks of the page sources, like test_connectivity_page.py."""
import re

from conftest import ROOT

HOMEPAGE = ROOT / "homepage"
PROJECT_PAGE = HOMEPAGE / "project.html"


def script_of(html):
    return "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S | re.I))


def manage_of(html):
    return re.search(r'<details[^>]*id="manage".*?</details>', html, re.S).group(0)


def members_pages():
    """The launcher pages whose script calls the platform's member routes."""
    # a link to the members page itself (/members.html) is not a call to the routes
    return [p for p in sorted(HOMEPAGE.glob("*.html")) if re.search(r"/members\b(?!\.html)", script_of(p.read_text()))]


def test_a_launcher_page_reads_and_writes_the_projects_members():
    pages = members_pages()
    assert pages, "no launcher page calls /api/projects/<slug>/members"
    script = script_of(pages[0].read_text())
    for method in ("POST", "PUT", "DELETE"):
        assert re.search(rf"['\"]{method}['\"]", script), f"{pages[0].name} never sends {method} to the member routes"


def test_the_members_page_says_why_the_last_owner_cannot_leave():
    pages = members_pages()
    assert pages, "no launcher page calls /api/projects/<slug>/members"
    script = script_of(pages[0].read_text())
    assert "detail" in script, "a refusal (the last owner) is shown with the platform's reason"


def test_the_manage_menu_links_the_members_page_for_owners_and_admins():
    pages = members_pages()
    assert pages, "no launcher page calls /api/projects/<slug>/members"
    html = PROJECT_PAGE.read_text()
    manage = manage_of(html)
    entry = re.search(r'<a\b[^>]*id="([^"]+)"[^>]*>\s*Members\s*</a>', manage)
    assert entry, "the Manage menu has no Members entry"
    tag = entry.group(0)
    assert "owner-only" in tag and "hidden" in tag, tag
    script = script_of(html)
    gate = script.index("if (a.admin || a.role === 'owner')")
    wiring = script.find(f"getElementById('{entry.group(1)}').href")
    assert wiring > gate, "the Members link is set inside the owner block"
    assert pages[0].name in script[wiring:wiring + 200], "the Members entry opens the members page"


def test_an_owner_sets_how_long_the_project_keeps_its_runs_on_the_members_page():
    page = (HOMEPAGE / "members.html").read_text()
    script = script_of(page)
    assert "/retention" in script, "the owner's page has no way to set how long runs are kept"
    assert "retention_days" in script, "the page does not show the period the project keeps"
    assert re.search(r'id="retention-days"[^>]*min="1"[^>]*max="3650"', page), "the field takes 1 to 3650 days"
