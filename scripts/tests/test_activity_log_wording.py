"""The activity log is the project's record of who did what. It serves audits, but not only them, so
the pages and the guide do not present it as an audit feature (2026-10-05)."""
import re

from conftest import ROOT


def visible_text(path):
    html = (ROOT / path).read_text()
    html = re.sub(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>|<!--.*?-->", "", html, flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", html)


def test_the_manage_menu_has_no_audit_group():
    assert not re.search(r"\baudit", visible_text("homepage/project.html"), re.I)


def test_the_activity_log_page_does_not_speak_of_audits_or_auditors():
    assert not re.search(r"\baudit", visible_text("homepage/logs.html"), re.I)


def test_the_guide_names_the_menu_as_it_is():
    assert "Manage > Audit" not in (ROOT / "docs/guide.md").read_text()
