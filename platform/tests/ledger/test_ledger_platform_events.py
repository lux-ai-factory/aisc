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


# phase 3 review M6, m15: every platform write has its event --------------------------------------------

def _events(store, pid, prefix):
    return [(e.action, e.item_id, e.details) for e in actions(store, pid) if e.action.startswith(prefix)]


def test_llm_provider_and_choice_changes_are_recorded(project, call, memory_ledger, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("PLATFORM_SECRETS_KEY", Fernet.generate_key().decode())
    slug = project["slug"]
    for method, path, body in [("PUT", "/llm/providers/ollama", {"base_url": "http://ollama.example:11434"}),
                               ("PUT", "/llm/systems/card_agent", {"provider": "ollama", "model": "llama3"}),
                               ("DELETE", "/llm/systems/card_agent", None),
                               ("DELETE", "/llm/providers/ollama", None)]:
        r = call(ADMIN, method, f"/projects/{slug}{path}", roles=ADMIN_ROLES, **({"json": body} if body else {}))
        assert r.status_code in (200, 201, 204), r.text
    relay_all(project["pid"])
    got = _events(memory_ledger, project["pid"], "llm.")
    assert [(a, i) for a, i, _ in got] == [("llm.provider.saved", "ollama"), ("llm.choice.saved", "card_agent"),
                                          ("llm.choice.removed", "card_agent"), ("llm.provider.removed", "ollama")]
    assert got[1][2] == {"provider_before": None, "provider_after": "ollama", "model_before": None,
                         "model_after": "llama3"}
    assert rejected_reasons(memory_ledger, project["pid"]) == []


def test_connection_changes_are_recorded(project, call, memory_ledger, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("PLATFORM_SECRETS_KEY", Fernet.generate_key().decode())
    slug = project["slug"]
    body = {"label": "Chat", "kind": "rest", "base_url": "https://chat.example.org", "path": "/ask",
            "body_template": {"question": "{{input}}"}, "response_path": "answer",
            "secret_header": "Authorization: Bearer {{secret}}", "secret": "sk-test-0123456789abcdefghijklmnop"}
    assert call(ADMIN, "PUT", f"/projects/{slug}/connections/chat", roles=ADMIN_ROLES, json=body).status_code == 200
    assert call(ADMIN, "POST", f"/projects/{slug}/connections/chat/link", roles=ADMIN_ROLES).status_code == 200
    assert call(ADMIN, "DELETE", f"/projects/{slug}/connections/chat", roles=ADMIN_ROLES).status_code == 204
    relay_all(project["pid"])
    got = _events(memory_ledger, project["pid"], "connection.")
    assert [(a, i) for a, i, _ in got] == [("connection.saved", "chat"), ("connection.saved", "chat"),
                                          ("connection.deleted", "chat")]
    assert got[0][2]["secret"] == "set" and "base_url" in got[0][2]["changed"]
    assert rejected_reasons(memory_ledger, project["pid"]) == []
    for x in entries(memory_ledger, log_of(project["pid"])):
        assert b"sk-test-0123" not in canonical(x.as_dict())


def test_a_connection_test_keeps_only_its_result(project, memory_ledger, mode):
    """The probe's answer can quote the system under test: the ledger keeps ok, refused or the error code."""
    from platform_service import connection_store

    mode("record")
    connection_store.save(project["pid"], "chat", {"label": "Chat", "kind": "rest", "base_url": "https://x.example"},
                          subject="t")
    connection_store.record_test(project["pid"], "chat", False, "boom: the system said a secret", result="timeout")
    rows = as_superuser_rows(project["pid"], "SELECT action, details FROM ledger.outbox WHERE action = 'connection.tested'")
    assert rows == [("connection.tested", {"result": "timeout"})]


def test_allowlist_changes_are_recorded(project, call, memory_ledger):
    slug = project["slug"]
    assert call(OWNER, "PUT", f"/projects/{slug}/allowed-hosts/chat.internal", json={"note": "the chatbot"}).status_code in (200, 201)
    assert call(OWNER, "DELETE", f"/projects/{slug}/allowed-hosts/chat.internal").status_code == 204
    relay_all(project["pid"])
    got = _events(memory_ledger, project["pid"], "allowlist.")
    assert got == [("allowlist.host.allowed", "chat.internal", {"note_before": None, "note_after": "the chatbot"}),
                   ("allowlist.host.removed", "chat.internal", {})]
    assert rejected_reasons(memory_ledger, project["pid"]) == []


def test_a_target_sync_is_recorded_with_its_counts(project, mode):
    from platform_service import target_store, targets

    mode("record")
    before = {t["key"]: t["label"] for t in target_store.all_targets(project["pid"])}
    targets.ensure_system(project["pid"], "the system")
    targets._record_sync(project["pid"], before)
    rows = as_superuser_rows(project["pid"], "SELECT details FROM ledger.outbox WHERE action = 'targets.synced'")
    assert rows == [({"added": len(target_store.all_targets(project["pid"])) - len(before), "renamed": 0},)]


@pytest.mark.parametrize("url, kept", [
    ("https://api.example.org/v1", "https://api.example.org/v1"),
    ("https://api.example.org/v1?api-key=sk-123", "https://api.example.org/v1#hmac:v1:"),
    ("https://user:pw@api.example.org:8443/v1", "https://api.example.org:8443/v1#hmac:v1:")])
def test_a_base_url_is_logged_without_its_query_or_user(project, url, kept):
    """m15: an OpenAI-compatible URL can carry its key in the query."""
    from platform_service import llm_store

    logged = llm_store.logged_url(project["pid"], url)
    assert logged.startswith(kept) and "sk-123" not in logged and "pw" not in logged


def rejected_reasons(store, pid):
    return [e.details["reason"] for e in entries(store, log_of(pid)) if e.action == "ledger.rejected"]


def as_superuser_rows(pid, statement):
    from tests.ledger.test_ledger_outbox import as_superuser

    return [tuple(r) for r in as_superuser(pid, statement)]


# phase 3 review m9, m11, m12 -------------------------------------------------------------------------

def test_a_platform_request_id_presented_on_another_route_is_refused(project, client, as_user, witnessed, mode):
    """m9: the person's own id, but witnessed for another platform route."""
    mode("enforce")
    request_id = witnessed(OWNER, "POST", "platform", f"/api/projects/{project['slug']}/members")
    r = client.put(f"/projects/{project['slug']}/members/{MEMBER}", json={"role": "viewer"},
                   headers={**as_user(OWNER), "X-AISC-Request-Id": request_id})
    assert r.status_code == 401


def test_in_record_mode_someone_elses_request_id_is_not_cited(project, client, as_user, witnessed, mode):
    """m9: in record, a presented id that fails the check is not used: the event cites no request (and
    the relay rejects it as missing_request), rather than another person's request."""
    mode("record")
    theirs = witnessed(MEMBER, "POST", "platform", f"/api/projects/{project['slug']}/members")
    other = "00000000-0000-0000-0000-0000000000e1"
    r = client.post(f"/projects/{project['slug']}/members", json={"subject": other, "role": "viewer"},
                    headers={**as_user(OWNER), "X-AISC-Request-Id": theirs})
    assert r.status_code in (200, 201)
    with psycopg.connect(DSN) as conn:
        cited = conn.execute("SELECT request_id FROM core.outbox WHERE action = 'member.added' AND item_id = %s",
                             (other,)).fetchone()[0]
    assert cited is None


def test_the_emit_functions_search_path_ends_with_pg_temp(project):
    """m11: a later unqualified name can't be shadowed by a caller's temporary table."""
    from tests.ledger.test_ledger_outbox import as_superuser

    [(config,)] = as_superuser(project["pid"], "SELECT proconfig FROM pg_proc WHERE oid = 'ledger.emit(jsonb)'::regprocedure")
    path = next(c for c in config if c.startswith("search_path="))
    assert path.replace(" ", "").endswith(",pg_temp")


@pytest.mark.parametrize("variant, reaches", [("pid_upper", True), ("pid_percent", False), ("slug_upper", False)])
def test_a_changed_case_or_percent_encoded_project_path(project, witnessed, memory_ledger, mode, variant, reaches):
    """Phase 2 m7, pinned. A pid is case-insensitive, so an upper-case pid is the same project. The witness
    neither decodes percent-encoding nor folds a slug's case: such a request lands in the platform log,
    and an event citing it is rejected for the project (it fails safe)."""
    from platform_service.ledger import registry
    from tests.ledger.test_ledger_outbox import emit

    mode("enforce")
    pid, slug = project["pid"], project["slug"]
    saved = registry.Action(name="qualification.test.saved", step=1, emitters=("qualification", "control_objectives"), item_type="t",
                            caused_by=(("qualification", "POST", r"^/qualification/p/[^/]+/x$"),
                                       ("control_objectives", "POST", r"^/control-objectives/p/[^/]+/x$")),
                            details_keys=(), per_request=1)
    if variant == "slug_upper":
        app, role, uri = "qualification", "qualification_rw", f"/qualification/p/{slug.upper()}/x"
    else:
        shown = pid.upper() if variant == "pid_upper" else f"%{ord(pid[0]):02X}" + pid[1:]
        app, role, uri = "control_objectives", "control_objectives_rw", f"/control-objectives/p/{shown}/x"
    with registry.override({saved.name: saved}):
        request_id = witnessed(MEMBER, "POST", app, uri)
        emit(pid, role, {"event_id": str(uuid.uuid4()), "request_id": request_id, "action": saved.name,
                         "item_type": "t", "item_id": "x"})
        relay_all(pid)
    accepted = [e for e in entries(memory_ledger, log_of(pid)) if e.action == saved.name]
    assert bool(accepted) is reaches
    assert rejected_reasons(memory_ledger, pid) == ([] if reaches else ["project_mismatch"])
