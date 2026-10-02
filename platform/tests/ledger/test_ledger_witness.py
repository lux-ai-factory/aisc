"""W1-W3: the witness (I1, I2, T5). Caddy calls GET /authz/witness for every request behind the
`protect` snippet; the platform verifies the person's token itself and records the request before the
app sees it. The app never names a person: it cites the request id the witness gave."""
from __future__ import annotations

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from platform_service.ledger.naming import PLATFORM_DB, database_name
from tests.conftest import ISSUER, needs_database
from tests.ledger.conftest import MEMBER, entries, witness_headers

pytestmark = needs_database


def _severity(pid):
    return f"/control-objectives/p/{pid}/projects/abc123/severity"


def test_a_write_with_a_valid_token_is_witnessed_and_numbered(client, token, project, memory_ledger, mode):
    mode("enforce")
    r = client.get("/authz/witness", headers=witness_headers(token(MEMBER, username="bob"), "POST",
                                                             _severity(project["pid"])))
    assert r.status_code == 200, r.text
    request_id = r.headers["X-AISC-Request-Id"]
    uuid.UUID(request_id)
    [e] = [x for x in entries(memory_ledger, database_name(project["pid"])) if x.action == "request.witnessed"]
    assert e.request_id == request_id
    assert (e.actor_kind, e.actor_sub, e.actor_name) == ("user", MEMBER, "bob")
    assert e.source_app == "control_objectives"
    assert e.details["method"] == "POST" and e.details["path"] == _severity(project["pid"])
    assert e.details["verified"] is True


def _forged(subject, **claims):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return jwt.encode({"sub": subject, "iss": ISSUER, "exp": int(time.time()) + 300, **claims}, other,
                      algorithm="RS256")


@pytest.mark.parametrize("kind", ["missing", "malformed", "wrong_key", "other_issuer", "expired"])
def test_enforce_refuses_a_bad_token_and_records_no_witness(client, key, project, memory_ledger, mode, kind):
    mode("enforce")
    bad = {
        "missing": None,
        "malformed": "not-a-token",
        "wrong_key": _forged(MEMBER),
        "other_issuer": jwt.encode({"sub": MEMBER, "iss": "http://evil/realms/aisc", "exp": int(time.time()) + 300},
                                   key, algorithm="RS256"),
        "expired": jwt.encode({"sub": MEMBER, "iss": ISSUER, "exp": int(time.time()) - 60}, key, algorithm="RS256"),
    }[kind]
    r = client.get("/authz/witness", headers=witness_headers(bad, "POST", _severity(project["pid"])))
    assert r.status_code == 401
    assert "X-AISC-Request-Id" not in r.headers
    assert not [x for x in entries(memory_ledger, database_name(project["pid"])) if x.action == "request.witnessed"]


def test_record_mode_lets_a_bad_token_through_and_says_so(client, project, memory_ledger, mode):
    mode("record")
    r = client.get("/authz/witness", headers=witness_headers(_forged(MEMBER), "POST", _severity(project["pid"])))
    assert r.status_code == 200
    [e] = [x for x in entries(memory_ledger, database_name(project["pid"])) if x.action == "request.unverified"]
    assert e.details["verified"] is False and e.actor_sub is None


def test_off_mode_records_nothing(client, token, project, memory_ledger, mode):
    mode("off")
    r = client.get("/authz/witness", headers=witness_headers(token(MEMBER), "POST", _severity(project["pid"])))
    assert r.status_code == 200
    assert entries(memory_ledger, database_name(project["pid"])) == []


def test_a_page_load_is_witnessed_as_page_opened(client, token, project, memory_ledger, mode):
    mode("enforce")
    uri = f"/control-objectives/p/{project['pid']}/projects/abc123"
    r = client.get("/authz/witness", headers=witness_headers(token(MEMBER), "GET", uri, dest="document"))
    assert r.status_code == 200
    [e] = [x for x in entries(memory_ledger, database_name(project["pid"])) if x.action == "page.opened"]
    assert e.actor_sub == MEMBER and e.details["path"] == uri


def test_a_background_read_is_not_recorded(client, token, project, memory_ledger, mode):
    mode("enforce")
    uri = f"/control-objectives/p/{project['pid']}/api/projects/abc123"
    r = client.get("/authz/witness", headers=witness_headers(token(MEMBER), "GET", uri, dest="empty"))
    assert r.status_code == 200
    assert entries(memory_ledger, database_name(project["pid"])) == []


@pytest.mark.parametrize("uri_of, app", [
    (lambda p: f"/p/{p['slug']}/evidence/links", "platform"),
    (lambda p: f"/api/projects/{p['slug']}/evidence/links", "platform"),
    (lambda p: f"/controls/p/{p['pid']}/submissions/x", "controls"),
    (lambda p: f"/qualification/p/{p['pid']}/qualify/new", "qualification"),
    (lambda p: f"/report-composer/p/{p['slug']}/layouts", "report_composer"),
])
def test_the_app_and_the_project_come_from_the_path(client, token, project, memory_ledger, mode, uri_of, app):
    mode("enforce")
    r = client.get("/authz/witness", headers=witness_headers(token(MEMBER), "POST", uri_of(project)))
    assert r.status_code == 200
    [e] = [x for x in entries(memory_ledger, database_name(project["pid"])) if x.action == "request.witnessed"]
    assert e.source_app == app


def test_a_request_outside_any_project_goes_to_the_platforms_log(client, token, memory_ledger, mode):
    mode("enforce")
    r = client.get("/authz/witness", headers=witness_headers(token(MEMBER), "POST", "/api/projects"))
    assert r.status_code == 200
    assert [x.action for x in entries(memory_ledger, PLATFORM_DB)] == ["request.witnessed"]
