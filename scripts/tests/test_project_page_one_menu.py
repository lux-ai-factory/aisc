"""The project page has one menu, Manage, in the top bar.

It shows the account to anyone signed in, the database diagrams to the project's members, and
pgAdmin, models and keys, and delete to admins."""
import re
from pathlib import Path

HTML = (Path(__file__).resolve().parents[2] / "homepage" / "project.html").read_text()
BODY = HTML[HTML.index("<body>"):]


def test_there_is_one_menu_and_it_is_in_the_top_bar():
    menus = re.findall(r"<details\b[^>]*>", BODY)
    assert len(menus) == 1, menus
    topbar = re.search(r'<div class="topbar">(.*?)\n</div>', BODY, re.S).group(1)
    assert 'id="manage"' in topbar
    assert not re.search(r"<summary>\s*Endpoints", BODY)


def test_manage_holds_the_endpoints_and_the_old_manage_items():
    menu = re.search(r'<details[^>]*id="manage".*?</details>', BODY, re.S).group(0)
    assert re.search(r"<summary>\s*Manage", menu)
    for item in ("Background tasks", "My account", 'id="inspect-schema"', 'id="inspect-pgadmin"',
                 'id="llm-settings"', 'id="delete-open"'):
        assert item in menu, item


def test_who_sees_what_is_unchanged():
    menu = re.search(r'<details[^>]*id="manage".*?</details>', BODY, re.S).group(0)
    assert not re.search(r'<details[^>]*id="manage"[^>]*\bhidden\b', menu), "the endpoints are for everyone signed in"
    assert re.search(r'<a id="inspect-schema"[^>]*class="member-only"[^>]*hidden', menu)
    for i in ("inspect-pgadmin", "llm-settings", "delete-open"):
        tag = re.search(r'<[a-z]+\b[^>]*id="' + i + r'"[^>]*>', menu).group(0)
        assert "admin-only" in tag and "hidden" in tag, tag
    assert "#manage .member-only" in HTML
    assert "#manage .admin-only" in HTML


def test_the_menu_uses_the_assessments_words_not_the_products():
    menu = re.search(r'<details[^>]*id="manage".*?</details>', BODY, re.S).group(0)
    visible = re.sub(r"<!--.*?-->", "", menu, flags=re.S)
    assert re.search(r'<a data-origin="keycloak" data-path="/realms/aisc/account">My account</a>', visible)
    assert re.search(r'<span class="group admin-only" hidden>Admin tools</span>\s*'
                     r'<a id="inspect-flower" class="admin-only" hidden[^>]*>Background tasks</a>', visible)
    assert '<span class="group admin-only" hidden>AI assistants</span>' in visible
    assert '<span class="group owner-only" hidden>Assessed system</span>' in visible
    for old in ("Endpoints", "Keycloak account", ">Flower<", "Agentic systems", "Systems under test", "Targets and endpoints"):
        assert old not in visible, old


def test_the_projects_page_says_create_and_my_account():
    index = (Path(__file__).resolve().parents[2] / "homepage" / "index.html").read_text()
    assert '<button class="newbtn" id="new-project">Create project</button>' in index
    assert "<h3>Create project</h3>" in index and "New project" not in index
    assert ">My account</a>" in index and "Keycloak account" not in index
    assert not re.search(r"<summary>\s*Endpoints", index)
