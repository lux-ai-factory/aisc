"""P1-P4: the platform's own events (I3, I7, I8; spec 4.3, 6.4). A platform write cites the request the
witness gave (Caddy forwards X-AISC-Request-Id). Member and project changes go through `core.outbox` in
the platform database, in their own transaction (R2.4). A card version is saved by the qualification
app on the person's behalf, so its cause is qualification's witnessed request (R1.6)."""
from __future__ import annotations

import uuid

import psycopg
import pytest

from platform_service.ledger.canonical import canonical
from tests.conftest import DSN
from tests.ledger.conftest import (ADMIN, ADMIN_ROLES, log_of, needs_db, MEMBER, OWNER, STRANGER, entries,
                                   person, relay_all)

pytestmark = needs_db


@pytest.fixture
def call(through_gateway, mode):
    """A platform API call that went through the launcher's gateway first (`/api/*`, stripped)."""
    mode("enforce")
    return through_gateway


def actions(store, pid):
    return [e for e in entries(store, log_of(pid))
            if not e.action.startswith(("request.", "page.", "ledger."))]


def test_member_changes_are_recorded_with_who_made_them(project, call, memory_ledger):
    slug, other = project["slug"], "00000000-0000-0000-0000-0000000000d4"
    assert call(OWNER, "POST", f"/projects/{slug}/members", json={"subject": other, "role": "viewer"}).status_code in (200, 201)
    assert call(OWNER, "PUT", f"/projects/{slug}/members/{other}", json={"role": "editor"}).status_code == 200
    assert call(OWNER, "DELETE", f"/projects/{slug}/members/{other}").status_code in (200, 204)
    relay_all(project["pid"])
    got = [(e.action, person(project["pid"], e.actor_ref)[0], e.item_id) for e in actions(memory_ledger, project["pid"])
           if e.action.startswith("member.") and e.item_id == other]
    assert got == [("member.added", OWNER, other), ("member.role_changed", OWNER, other),
                   ("member.removed", OWNER, other)]
    changed = next(e for e in actions(memory_ledger, project["pid"]) if e.action == "member.role_changed")
    assert {changed.details.get("role_before"), changed.details.get("role_after")} == {"viewer", "editor"}


def test_a_member_change_that_fails_leaves_no_event(project, call, memory_ledger):
    r = call(OWNER, "PUT", f"/projects/{project['slug']}/members/00000000-0000-0000-0000-0000000000ee",
             json={"role": "boss"})                                  # no such role: refused, nothing changed
    assert r.status_code >= 400
    relay_all(project["pid"])
    assert [e for e in actions(memory_ledger, project["pid"]) if e.action.startswith("member.")
            and e.item_id.endswith("ee")] == []


def test_an_llm_key_is_recorded_by_its_keyed_fingerprint_only(project, call, memory_ledger, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("PLATFORM_SECRETS_KEY", Fernet.generate_key().decode())   # the keys are encrypted at rest
    secret = "sk-test-0123456789abcdefghijklmnop"
    r = call(ADMIN, "PUT", f"/projects/{project['slug']}/llm/providers/openai", json={"api_key": secret},
             roles=ADMIN_ROLES)                                     # only a platform admin manages keys
    assert r.status_code in (200, 201), r.text
    relay_all(project["pid"])
    [e] = [e for e in actions(memory_ledger, project["pid"]) if e.action == "llm.provider.saved"]
    assert e.details["key"].startswith("hmac:v1:")                       # the project's fingerprint key
    for x in entries(memory_ledger, log_of(project["pid"])):
        assert secret.encode() not in canonical(x.as_dict())


def test_a_platform_write_without_a_witnessed_request_is_refused_in_enforce(project, client, as_user, mode):
    mode("enforce")
    r = client.post(f"/projects/{project['slug']}/members", json={"subject": MEMBER, "role": "viewer"},
                    headers=as_user(OWNER))
    assert r.status_code == 401


def test_a_request_id_presented_by_someone_else_is_refused(project, client, as_user, witnessed, mode):
    """Inside the network the id and the token can travel apart: the platform checks they match (R1.5)."""
    mode("enforce")
    owners = witnessed(OWNER, "POST", "platform", f"/api/projects/{project['slug']}/members")
    r = client.post(f"/projects/{project['slug']}/members", json={"subject": STRANGER, "role": "viewer"},
                    headers={**as_user(MEMBER), "X-AISC-Request-Id": owners})
    assert r.status_code == 401


def test_a_card_version_saved_by_step_1_is_the_persons(project, client, as_user, witnessed, memory_ledger, mode):
    """The browser submits a server action to qualification; qualification calls the platform with the
    person's token and the forwarded id (06-spike.md G11)."""
    mode("enforce")
    submit = witnessed(MEMBER, "POST", "qualification", f"/qualification/p/{project['slug']}/qualify/new",
                       next_action="60b7a2efb1d3fb3ac1825abb501965ed20949d5936")
    r = client.post(f"/projects/{project['slug']}/system-versions", json={"name": "MCAS", "version": "1.2.0"},
                    headers={**as_user(MEMBER), "X-AISC-Request-Id": submit})
    assert r.status_code in (200, 201), r.text
    relay_all(project["pid"])
    [e] = [e for e in actions(memory_ledger, project["pid"]) if e.action == "card_version.created"]
    assert (e.source_app, e.request_id) == ("platform", submit)
    assert person(project["pid"], e.actor_ref)[0] == MEMBER and e.item_version == "1"


def _project_db_event(project, witnessed):
    """An event in the project database's own outbox, which the drop would destroy."""
    from tests.ledger.test_ledger_outbox import emit

    request_id = witnessed(MEMBER, "POST", "control_objectives",
                           f"/control-objectives/p/{project['pid']}/api/projects/a1/ratings")
    emit(project["pid"], "control_objectives_rw", {"event_id": str(uuid.uuid4()),
                                                   "request_id": request_id, "action": "risk.rated",
                                                   "item_type": "risk", "item_id": "r1"})


def test_a_project_db_with_undelivered_events_is_not_dropped_until_they_are_delivered(project, call, witnessed,
                                                                                      memory_ledger):
    _project_db_event(project, witnessed)
    memory_ledger.down = True                                       # the drain can't deliver
    r = call(ADMIN, "DELETE", f"/projects/{project['slug']}", roles=ADMIN_ROLES, json={"confirm_name": project["name"]})
    assert r.status_code == 409 and "undelivered" in r.text.lower()
    memory_ledger.down = False
    assert call(ADMIN, "DELETE", f"/projects/{project['slug']}", roles=ADMIN_ROLES, json={"confirm_name": project["name"]}).status_code in (200, 204)
    relay_all(project["pid"])
    kept = [e.action for e in entries(memory_ledger, log_of(project["pid"]))]
    assert "risk.rated" in kept and "project.deleted" in kept       # the log outlives the project (D2)


def test_pending_platform_database_rows_never_block_a_delete(project, call, memory_ledger):
    """Member events and the delete's own witness and `project.deleted` live in the platform database,
    which the drop doesn't touch: they are delivered later (spec 6.4, third review M3)."""
    call(OWNER, "POST", f"/projects/{project['slug']}/members",
         json={"subject": "00000000-0000-0000-0000-0000000000d5", "role": "viewer"})
    memory_ledger.down = True
    assert call(ADMIN, "DELETE", f"/projects/{project['slug']}", roles=ADMIN_ROLES, json={"confirm_name": project["name"]}).status_code in (200, 204)
    memory_ledger.down = False
    relay_all(project["pid"])
    kept = [e.action for e in entries(memory_ledger, log_of(project["pid"]))]
    assert "member.added" in kept and "project.deleted" in kept


def test_member_events_wait_in_the_platform_databases_outbox(project, call):
    call(OWNER, "POST", f"/projects/{project['slug']}/members",
         json={"subject": "00000000-0000-0000-0000-0000000000d6", "role": "viewer"})
    with psycopg.connect(DSN) as conn:
        [(n,)] = conn.execute("SELECT count(*) FROM core.outbox WHERE action = 'member.added'"
                              " AND project_pid = %s", (project["pid"],)).fetchall()
    assert n >= 1


# phase 3 review M5: the drain closes the database to the apps before it counts -----------------------

def _delete(call, project):
    return call(ADMIN, "DELETE", f"/projects/{project['slug']}", roles=ADMIN_ROLES, json={"confirm_name": project["name"]})


def test_a_delete_while_another_role_is_connected_is_refused_and_changes_nothing(project, call, memory_ledger):
    """An app with an open session could still commit an event after the count; the platform can't end
    another role's session, so it refuses (409) and lets the database be used again."""
    from platform_service import projectdb
    from tests.ledger.test_ledger_outbox import connect

    def acl():
        with psycopg.connect(DSN) as conn:
            return set(conn.execute("SELECT a.grantee, a.privilege_type FROM pg_database d"
                                    " CROSS JOIN LATERAL aclexplode(d.datacl) a WHERE d.datname = %s",
                                    (projectdb.database_name(project["pid"]),)).fetchall())
    before = acl()
    with connect(project["pid"]) as app_session:                       # another role, connected
        app_session.execute("SELECT 1")
        r = _delete(call, project)
        assert r.status_code == 409 and "in use" in r.text.lower()
    assert acl() == before                                              # every app may connect again
    with connect(project["pid"]) as again:                              # still usable, and still there
        again.execute("SELECT 1")
    with psycopg.connect(DSN) as conn:
        assert conn.execute("SELECT 1 FROM core.project WHERE pid = %s", (project["pid"],)).fetchone()
    assert _delete(call, project).status_code in (200, 204)


def test_during_the_drain_no_new_app_session_can_start(project, call, memory_ledger, monkeypatch):
    """CONNECT is revoked before the count: an app trying to connect meanwhile is refused."""
    from psycopg.conninfo import make_conninfo

    from platform_service import projectdb
    from platform_service.ledger import relay

    tried = []
    real = relay.relay_once

    def app_connects_meanwhile(pid=None):
        dsn = make_conninfo(DSN, user="controls_rw", password="controls_rw", dbname=projectdb.database_name(pid))
        try:
            psycopg.connect(dsn).close()
            tried.append("connected")
        except psycopg.OperationalError as exc:
            tried.append("refused" if "permission denied" in str(exc).lower() else f"other: {exc}")
        return real(pid)
    monkeypatch.setattr(relay, "relay_once", app_connects_meanwhile)
    assert _delete(call, project).status_code in (200, 204)
    assert tried == ["refused"], tried


def test_a_drain_that_cannot_count_refuses_the_drop(project, call, memory_ledger, monkeypatch):
    """Review M5: a failure to count is not "nothing to lose" while the database exists."""
    from platform_service import app

    def cannot(_pid):
        raise psycopg.OperationalError("too many connections (test)")
    monkeypatch.setattr(app, "projectdb_connection", cannot)
    assert _delete(call, project).status_code == 503
    with psycopg.connect(DSN) as conn:
        assert conn.execute("SELECT 1 FROM core.project WHERE pid = %s", (project["pid"],)).fetchone()
