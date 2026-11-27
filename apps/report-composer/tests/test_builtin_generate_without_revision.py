"""A built-in layout has no revision, and its own generate form produces a report.

The form on a layout's page says which revision the person is looking at, so a report is never of another
one. A built-in layout has no revision: its form sends none, and "no revision" is accepted for a built-in
layout only. A stored layout's request without a revision is refused with `token_required`. The form is
posted here as a browser posts it: every field the page draws, and the button that was clicked. Database
tests, fake renderer.
"""
from urllib.parse import parse_qs, urlsplit

import pytest
from bs4 import BeautifulSoup

from conftest import IDS, PDF, error_code, new_layout
from v2_fakes import client_v2, fake_v2, v2blk  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]

B = "builtin-summary"


def generate_form(client_v2, auth, layout_id, fmt="pdf"):
    """(where the page's Generate and download button posts, the fields a browser sends with it)."""
    page = client_v2.get(f"/p/alpha/layouts/{layout_id}", headers=auth("alice"))
    assert page.status_code == 200, page.text[:300]
    form = BeautifulSoup(page.text, "html.parser").find("form", attrs={"data-control": "preview-with"})
    button = form.find("button", attrs={"name": "format", "value": fmt})
    assert button is not None and button["formmethod"] == "post", "the page has no Generate and download button"
    fields = {}
    for control in form.find_all(["input", "select"]):
        if not control.get("name"):
            continue
        if control.name == "select":
            chosen = control.find("option", selected=True) or control.find("option")
            fields[control["name"]] = chosen["value"]
        elif control.get("type") == "checkbox":
            if control.has_attr("checked"):
                fields[control["name"]] = "on"
        else:
            fields[control["name"]] = control.get("value", "")
    fields[button["name"]] = button["value"]
    return button["formaction"], fields


def reports_of(client_v2, auth, layout_id) -> list:
    return client_v2.get(f"/api/p/alpha/layouts/{layout_id}/reports", headers=auth("alice")).json()


def why_not(response) -> str:
    """The message a refused generation goes back to the page with, or the answer's status."""
    refused = parse_qs(urlsplit(response.headers.get("location", "")).query).get("report_error")
    return refused[0] if refused else f"status {response.status_code}"


def test_a_built_in_layouts_own_form_produces_a_report(client_v2, auth):
    action, fields = generate_form(client_v2, auth, B)
    answer = client_v2.post(action, data=fields, headers=auth("alice"), follow_redirects=False)
    assert (answer.status_code, answer.content) == (200, PDF), (
        f"the built-in layout's own form was answered with: {why_not(answer)}")


def test_a_built_in_layouts_form_sends_no_revision(client_v2, auth):
    _, fields = generate_form(client_v2, auth, B)
    assert "revision" not in fields, f"the form of a layout without a revision sends revision={fields['revision']!r}"


def test_a_stored_layout_without_a_revision_is_still_refused(client_v2, auth):
    own = new_layout(client_v2, auth, name="Own", blocks=[v2blk("cover"), v2blk("free_text", text="x")])["id"]
    action, fields = generate_form(client_v2, auth, own)
    fields.pop("revision")
    answer = client_v2.post(action, data=fields, headers=auth("alice"), follow_redirects=False)
    assert reports_of(client_v2, auth, own) == [], "a report was generated without the revision the person saw"
    assert answer.content != PDF and answer.status_code != 200
