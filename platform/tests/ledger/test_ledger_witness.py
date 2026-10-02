"""W1-W6: the witness (I1, I2, I9, I10, T5, T6, T18-T20, T23), called exactly as Caddy calls it
(06-spike.md G8). The platform verifies the person's token itself and records the request in its
Postgres before the app sees it; immudb is not on this path (M16). The app never names a person: it
cites the request id the witness gave."""
from __future__ import annotations

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from tests.conftest import ISSUER, needs_database
from tests.ledger.conftest import (GATEWAY_CLIENT, MEMBER, OWNER, STRANGER, caddy_headers, entries, person,
                                   record)

pytestmark = needs_database


def ratings(pid):
    return f"/control-objectives/p/{pid}/api/projects/abc123/ratings"


# W1: a write with a valid token ---------------------------------------------------------------------

def test_a_write_is_witnessed_in_postgres_and_numbered(call_witness, gateway_token, project, memory_ledger, mode):
    mode("enforce")
    r = call_witness(gateway_token(MEMBER, username="bob"), "POST", "control_objectives", ratings(project["pid"]))
    assert r.status_code == 200, r.text
    rec = record(r.headers["X-AISC-Request-Id"])
    assert (rec.app, rec.method, rec.route_path, rec.project_pid) == ("control_objectives", "POST",
                                                                      ratings(project["pid"]), project["pid"])
    assert rec.verified is True and rec.member is True
    assert person(project["pid"], rec.actor_ref) == (MEMBER, "bob")
    assert entries(memory_ledger, "ledgerplatform") == []          # immudb is not on the request path


def test_the_record_holds_no_subject_and_no_name(call_witness, gateway_token, project, mode):
    mode("enforce")
    r = call_witness(gateway_token(MEMBER, username="bob"), "POST", "control_objectives", ratings(project["pid"]))
    rec = record(r.headers["X-AISC-Request-Id"])
    assert MEMBER not in rec.actor_ref and "bob" not in str(vars(rec).values())


def test_every_witnessed_request_gets_its_own_id(call_witness, gateway_token, project, mode):
    mode("enforce")
    ids = {call_witness(gateway_token(MEMBER), "POST", "control_objectives", ratings(project["pid"]))
           .headers["X-AISC-Request-Id"] for _ in range(3)}
    assert len(ids) == 3


# W2: the gateway secret (T18) -----------------------------------------------------------------------

@pytest.mark.parametrize("gateway", [None, "", "guess", "test-gateway-secret-0123456789abcdeX"])
def test_a_call_without_the_gateway_secret_is_refused_and_leaves_no_record(call_witness, gateway_token, project,
                                                                           mode, gateway):
    mode("record")                                                  # even in record mode
    r = call_witness(gateway_token(MEMBER), "POST", "control_objectives", ratings(project["pid"]), gateway=gateway)
    assert r.status_code == 401
    assert "X-AISC-Request-Id" not in r.headers


def test_the_platform_refuses_to_witness_without_a_configured_secret(call_witness, gateway_token, project, mode,
                                                                     monkeypatch):
    mode("enforce")
    monkeypatch.delenv("AISC_WITNESS_GATEWAY_SECRET")
    r = call_witness(gateway_token(MEMBER), "POST", "control_objectives", ratings(project["pid"]), gateway="")
    assert r.status_code == 503


@pytest.mark.parametrize("app", [None, "", "evil", "control-objectives"])
def test_an_app_name_outside_the_known_apps_is_refused(client, gateway_token, project, mode, app):
    mode("enforce")
    headers = caddy_headers(gateway_token(MEMBER), "POST", "control_objectives", ratings(project["pid"]))
    if app is None:
        del headers["X-AISC-App"]
    else:
        headers["X-AISC-App"] = app
    assert client.get("/authz/witness", headers=headers).status_code == 400


# W3: tokens (T5, T20, R1.12, R1.15) -----------------------------------------------------------------

def _forged(subject, **claims):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    body = {"sub": subject, "iss": ISSUER, "azp": GATEWAY_CLIENT, "exp": int(time.time()) + 300, **claims}
    return jwt.encode(body, other, algorithm="RS256")


def _bad_token(kind, key, gateway_token):
    now = int(time.time())
    return {
        "missing": None,
        "malformed": "not-a-token",
        "wrong_key": _forged(MEMBER),
        "other_issuer": gateway_token(MEMBER, iss="http://evil/realms/aisc"),
        "expired": gateway_token(MEMBER, exp=now - 60),
        "not_yet": gateway_token(MEMBER, nbf=now + 120),
        "other_client": gateway_token(MEMBER, azp="some-other-client"),
    }[kind]


KINDS = ["missing", "malformed", "wrong_key", "other_issuer", "expired", "not_yet", "other_client"]


@pytest.mark.parametrize("kind", KINDS)
def test_enforce_refuses_a_bad_token(call_witness, key, gateway_token, project, mode, kind):
    mode("enforce")
    r = call_witness(_bad_token(kind, key, gateway_token), "POST", "control_objectives", ratings(project["pid"]))
    assert r.status_code == 401
    assert "X-AISC-Request-Id" not in r.headers


@pytest.mark.parametrize("kind", KINDS)
def test_record_mode_lets_a_bad_token_through_and_says_so(call_witness, key, gateway_token, project, mode, kind):
    mode("record")
    r = call_witness(_bad_token(kind, key, gateway_token), "POST", "control_objectives", ratings(project["pid"]))
    assert r.status_code == 200
    rec = record(r.headers["X-AISC-Request-Id"])                    # an id even now, so Caddy overwrites (G3)
    assert rec.verified is False and rec.reason and rec.actor_ref is None


def test_a_token_just_past_expiry_is_still_accepted_within_the_leeway(call_witness, gateway_token, project, mode,
                                                                      settings):
    mode("enforce")
    token = gateway_token(MEMBER, exp=int(time.time()) - settings.LEEWAY.total_seconds() // 2)
    assert call_witness(token, "POST", "control_objectives", ratings(project["pid"])).status_code == 200


def test_a_bearer_token_for_the_same_person_is_fine(call_witness, gateway_token, token, project, mode):
    mode("enforce")
    r = call_witness(gateway_token(MEMBER), "POST", "engine", "/api/v1/project/x", bearer=token(MEMBER),
                     project_header=project["pid"])
    assert r.status_code == 200


def test_a_bearer_token_for_someone_else_is_refused_in_enforce(call_witness, gateway_token, token, project, mode):
    mode("enforce")
    r = call_witness(gateway_token(MEMBER), "POST", "engine", "/api/v1/project/x", bearer=token(OWNER),
                     project_header=project["pid"])
    assert r.status_code == 401


def test_a_bearer_token_for_someone_else_is_marked_in_record(call_witness, gateway_token, token, project, mode):
    mode("record")
    r = call_witness(gateway_token(MEMBER), "POST", "engine", "/api/v1/project/x", bearer=token(OWNER),
                     project_header=project["pid"])
    assert r.status_code == 200
    rec = record(r.headers["X-AISC-Request-Id"])
    assert (rec.verified, rec.reason) == (False, "token_mismatch")


def test_a_forged_bearer_next_to_a_good_gateway_token_is_refused(call_witness, gateway_token, project, mode):
    mode("enforce")
    r = call_witness(gateway_token(MEMBER), "POST", "engine", "/api/v1/project/x", bearer=_forged(MEMBER),
                     project_header=project["pid"])
    assert r.status_code == 401


# W4: which app, which project (T6, T23, I9; G1) ------------------------------------------------------

@pytest.mark.parametrize("app, uri_of", [
    ("control_objectives", lambda p: f"/control-objectives/p/{p['pid']}/api/projects/a1/ratings"),
    ("report_composer", lambda p: f"/report-composer/p/{p['slug']}/layouts"),
    ("qualification", lambda p: f"/qualification/p/{p['slug']}/qualify/new"),
    ("controls", lambda p: f"/controls/p/{p['slug']}/submissions/s1"),
    ("platform", lambda p: f"/api/projects/{p['slug']}/evidence"),
])
def test_the_project_comes_from_the_unstripped_path_by_the_apps_rule(witnessed, project, mode, app, uri_of):
    mode("enforce")
    rec = record(witnessed(MEMBER, "POST", app, uri_of(project)))
    assert (rec.app, rec.project_pid) == (app, project["pid"])


def test_the_stripped_uri_alone_names_no_project(client, gateway_token, project, mode):
    """Caddy's X-Forwarded-Uri for control objectives is /p/{pid}/...: alone it can't say which app."""
    mode("enforce")
    headers = caddy_headers(gateway_token(MEMBER), "POST", "control_objectives", ratings(project["pid"]))
    del headers["X-AISC-Original-Uri"]
    assert client.get("/authz/witness", headers=headers).status_code == 400


def test_the_engine_names_its_project_in_a_header(witnessed, project, mode):
    mode("enforce")
    rec = record(witnessed(MEMBER, "PATCH", "engine", "/api/v1/project/abc", project_header=project["pid"]))
    assert rec.project_pid == project["pid"]


def test_an_unknown_project_id_goes_to_the_platform_log_and_creates_nothing(witnessed, mode):
    from platform_service.ledger import provision

    mode("enforce")
    ghost = str(uuid.uuid4())
    before = provision.assigned()
    rec = record(witnessed(MEMBER, "POST", "control_objectives", ratings(ghost)))
    assert rec.project_pid is None
    assert provision.assigned() == before                          # no database for a random pid (T23)


def test_a_strangers_request_never_enters_the_projects_log(witnessed, project, mode):
    mode("enforce")
    rec = record(witnessed(STRANGER, "POST", "control_objectives", ratings(project["pid"])))
    assert (rec.project_pid, rec.member) == (None, False)


def test_a_request_outside_any_project_goes_to_the_platform_log(witnessed, mode):
    mode("enforce")
    rec = record(witnessed(MEMBER, "POST", "platform", "/api/projects"))
    assert rec.project_pid is None and rec.app == "platform"


# W5: what is kept of the request (I8, G6, G10) -------------------------------------------------------

def test_the_query_string_is_kept_only_as_a_keyed_fingerprint(witnessed, project, mode):
    mode("enforce")
    secret = "tok-abcdef0123456789"
    rec = record(witnessed(MEMBER, "POST", "qualification", f"/qualification/p/{project['slug']}/x?token={secret}"))
    assert "?" not in rec.route_path and secret not in str(vars(rec).values())
    assert rec.query_hmac and rec.query_hmac.startswith("hmac:")


def test_a_server_action_id_is_recorded(witnessed, project, mode):
    mode("enforce")
    action = "60b7a2efb1d3fb3ac1825abb501965ed20949d5936"
    rec = record(witnessed(MEMBER, "POST", "qualification", f"/qualification/p/{project['slug']}/qualify/new",
                           next_action=action))
    assert rec.next_action == action


def test_off_mode_does_not_witness(call_witness, gateway_token, project, mode):
    """With LEDGER_MODE=off the Caddy snippet is empty (LEDGER_GATEWAY=off); a stray call gets no id."""
    mode("off")
    r = call_witness(gateway_token(MEMBER), "POST", "control_objectives", ratings(project["pid"]))
    assert r.status_code == 200 and "X-AISC-Request-Id" not in r.headers


# W6: the witness never waits on immudb (I6, M16) -----------------------------------------------------

def test_the_witness_works_while_immudb_is_down(call_witness, gateway_token, project, memory_ledger, mode):
    mode("enforce")
    memory_ledger.down = True
    r = call_witness(gateway_token(MEMBER), "POST", "control_objectives", ratings(project["pid"]))
    assert r.status_code == 200 and record(r.headers["X-AISC-Request-Id"]) is not None
