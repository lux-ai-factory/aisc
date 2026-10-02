"""P1: the platform's own events (I7, I8). Each platform write cites the request the witness gave
(Caddy forwards X-AISC-Request-Id); after the relay, the project's ledger holds the event with the
witness's actor, and no secret appears anywhere in it."""
from __future__ import annotations

import pytest

from platform_service.ledger import relay
from platform_service.ledger.canonical import canonical
from platform_service.ledger.naming import database_name
from tests.conftest import needs_database
from tests.ledger.conftest import MEMBER, OWNER, entries

pytestmark = needs_database


@pytest.fixture
def call(client, as_user, witnessed, mode):
    """A platform API call that went through the witness first, as behind Caddy."""
    mode("enforce")

    def run(subject, method, path, **kwargs):
        request_id = witnessed(subject, method, "/api" + path)
        headers = {**as_user(subject), "X-AISC-Request-Id": request_id}
        return client.request(method, path, headers=headers, **kwargs)
    return run


def actions(store, pid):
    return [e for e in entries(store, database_name(pid)) if not e.action.startswith(("request.", "page."))]


def test_member_changes_are_recorded_with_who_made_them(project, call, memory_ledger):
    slug = project["slug"]
    other = "00000000-0000-0000-0000-0000000000d4"
    assert call(OWNER, "POST", f"/projects/{slug}/members", json={"subject": other, "role": "viewer"}).status_code in (200, 201)
    assert call(OWNER, "PUT", f"/projects/{slug}/members/{other}", json={"role": "editor"}).status_code == 200
    assert call(OWNER, "DELETE", f"/projects/{slug}/members/{other}").status_code in (200, 204)
    relay.relay_once(project["pid"])
    got = [(e.action, e.actor_sub, e.item_id) for e in actions(memory_ledger, project["pid"])
           if e.action.startswith("member.")]
    assert got == [("member.added", OWNER, other), ("member.role_changed", OWNER, other),
                   ("member.removed", OWNER, other)]
    changed = next(e for e in actions(memory_ledger, project["pid"]) if e.action == "member.role_changed")
    assert changed.details == {"role_before": "viewer", "role_after": "editor"}


def test_an_llm_key_is_recorded_by_its_fingerprint_only(project, call, memory_ledger, monkeypatch):
    secret = "sk-test-0123456789abcdefghijklmnop"
    r = call(OWNER, "PUT", f"/projects/{project['slug']}/llm/providers/openai", json={"api_key": secret})
    assert r.status_code in (200, 201), r.text
    relay.relay_once(project["pid"])
    [e] = [e for e in actions(memory_ledger, project["pid"]) if e.action == "llm.provider.saved"]
    assert e.details["key"].startswith("sha256:")
    for x in entries(memory_ledger, database_name(project["pid"])):
        assert secret.encode() not in canonical(x.as_dict())


def test_a_platform_write_without_a_witnessed_request_is_refused_in_enforce(project, client, as_user, mode):
    mode("enforce")
    r = client.post(f"/projects/{project['slug']}/members", json={"subject": MEMBER, "role": "viewer"},
                    headers=as_user(OWNER))
    assert r.status_code == 401 and "witness" in r.text


def test_a_card_version_is_recorded(project, call, memory_ledger):
    r = call(OWNER, "POST", f"/projects/{project['slug']}/system-versions", json={"name": "MCAS", "version": "1.2.0"})
    assert r.status_code in (200, 201), r.text
    relay.relay_once(project["pid"])
    [e] = [e for e in actions(memory_ledger, project["pid"]) if e.action == "card_version.created"]
    assert e.actor_sub == OWNER and e.item_version == "1"
