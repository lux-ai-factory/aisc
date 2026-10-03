"""The project page has one menu, Manage, in the top bar.

It shows the endpoints to anyone signed in, the database diagrams to the project's members, and
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
    for item in ("Flower", "Keycloak account", 'id="inspect-schema"', 'id="inspect-pgadmin"',
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
