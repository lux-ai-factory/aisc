"""A connection saved from a page opened earlier does not replace a colleague's change.

A opens the connection's editor, B opens it, B saves, A saves what A's page still shows. A's save must be
refused with `changed_since_opened` and B's work must still be stored. In order, not at once: a lost update
needs no true concurrency.

Expected to fail until the Connections page sends back the token it was drawn with: the spec of that page
closes these tests and removes the mark. Strict, so the suite turns red the day one passes with the mark on.
"""
from __future__ import annotations

import pytest

from tests.conftest import needs_database, one
from tests.connection_support import engine_component, new_secret
from tests.test_connections import _env, base, rest_body, stub  # noqa: F401  (fixtures)
from tests.two_sessions import two_editors_who_administer  # noqa: F401  (fixture)

pytestmark = [needs_database,
              pytest.mark.xfail(strict=True, reason="until the Connections page (Manage > Connections) sends its "
                                                    "opened-on token and the platform refuses a save without the "
                                                    "latest one")]

NAME = "mcas-chat"
#: what B changes while A's editor is open
B_CHANGES = {"path": "/v2/chat", "timeout_s": 30}


def opened(session, project) -> dict:
    """The connection as its editor shows it to `session`: the row of the list the page loads."""
    rows = session.get(base(project)).json()["connections"]
    return next(row for row in rows if row["name"] == NAME)


def editor_form(row: dict, **typed) -> dict:
    """What the Connections page sends for a REST connection whose editor was filled from `row`: every field
    of the form, no key unless one is typed, and the opened-on token when the row carries one."""
    body = {"label": row["label"], "kind": row["kind"], "base_url": row["base_url"], "timeout_s": row["timeout_s"],
            "headers": row["headers"] or {}, "secret_header": row["secret_header"] or None,
            "supports_tools": False, "supports_logprobs": False,
            "method": row["method"], "path": row["path"], "body_template": row["body_template"],
            "response_path": row["response_path"] or None, "refusal": row["refusal"]}
    if "token" in row:
        body["token"] = row["token"]
    body.update(typed)
    return body


@pytest.fixture
def stale_save(two_editors_who_administer, stub):
    """A's save of an editor opened before B's save: (A's answer, the project, A, B)."""
    project, a, b = (two_editors_who_administer.project, two_editors_who_administer.a,
                     two_editors_who_administer.b)
    engine_component(stub, project["pid"])
    made = a.put(f"{base(project)}/{NAME}", json=rest_body(stub, secret=new_secret()))
    assert made.status_code == 200, made.text
    seen_by_a = opened(a, project)
    saved_by_b = b.put(f"{base(project)}/{NAME}", json=editor_form(opened(b, project), **B_CHANGES))
    assert saved_by_b.status_code == 200, saved_by_b.text
    answer = a.put(f"{base(project)}/{NAME}", json=editor_form(seen_by_a, label="MCAS chat (renamed)"))
    return answer, project, a, b


def test_the_save_from_the_page_opened_earlier_is_refused(stale_save):
    answer, *_ = stale_save
    assert answer.status_code == 409, f"a save over a colleague's change answered {answer.status_code}"
    assert answer.json()["detail"]["code"] == "changed_since_opened"


def test_the_colleagues_change_is_still_stored(stale_save, dsn):
    _, project, _, b = stale_save
    path, timeout_s, label = one(dsn, project, "select path, timeout_s, label from connection.endpoint"
                                               " where name = %s", (NAME,))
    assert (path, timeout_s) == (B_CHANGES["path"], B_CHANGES["timeout_s"]), (
        f"{b.name}'s path and timeout were replaced by ({path!r}, {timeout_s})")
    assert label == "MCAS chat", f"the refused save still wrote its label, {label!r}"


def test_the_refusal_names_the_colleague_who_saved(stale_save):
    answer, _, _, b = stale_save
    assert answer.status_code == 409, f"a save over a colleague's change answered {answer.status_code}"
    assert answer.json()["detail"]["current"]["changed_by"] == b.name
