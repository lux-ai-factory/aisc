"""PR1-PR8: minimisation and keys (I8, I10, T22, D9; spec 6.1, 7.5; second review N4, N5).

- immudb holds an `actor_ref`, never a subject or a name. The reference is **random**, one per
  (project, person), so no key and no list of users can recompute it: deleting the mapping row
  really erases the link.
- The mapping row carries a MAC under the project's mapping key, so a swapped row is still detected.
- Keys are derived per project and per purpose (HKDF) from versioned master keys
  (`PLATFORM_LEDGER_KEYS="v1:...,v2:..."`). Every digest says its version (`hmac:v1:...`), new ones use
  the newest, and old ones keep checking after a rotation.
- Apps send plain content; the platform computes every keyed digest (N4). An auditor gets the
  project's own content key in the export, never another project's, never the master.
"""
from __future__ import annotations

import uuid

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from platform_service.ledger import actors, secrets
from platform_service.ledger.canonical import canonical
from tests.ledger.conftest import LEDGER_KEYS, MEMBER, OWNER, STRANGER, entries, log_of, needs_db, person, relay_all
from tests.ledger.test_ledger_outbox import emit

pytestmark = needs_db
ROOT = Path(__file__).resolve().parents[3]
PURPOSES = ("content", "state", "query", "mapping", "fingerprint")


def rated(request_id, n=1, **over):
    e = {"event_id": str(uuid.uuid4()), "request_id": request_id, "action": "risk.rated",
         "item_type": "risk", "item_id": f"r{n}", "content": {"answer": "yes"}}
    e.update(over)
    return e


@pytest.fixture
def rate(project, witnessed, mode):
    mode("enforce")

    def run(subject=MEMBER, n=1, pid=None, **over):
        pid = pid or project["pid"]
        request_id = witnessed(subject, "POST", "control_objectives",
                               f"/control-objectives/p/{pid}/api/projects/a1/ratings", username="bob")
        emit(pid, "control_objectives_rw", rated(request_id, n, **over))
        relay_all(pid)
        return next((e for e in entries_of(pid) if e.action == "risk.rated" and e.item_id == f"r{n}"), None)
    return run


def entries_of(pid):
    from platform_service import ledger

    return entries(ledger.current(), log_of(pid))


# PR1-PR4: the actor reference -----------------------------------------------------------------------

def test_immudb_never_holds_the_subject_or_the_name(project, rate):
    rate()
    for e in entries_of(project["pid"]):
        raw = canonical(e.as_dict())
        assert MEMBER.encode() not in raw and b"bob" not in raw


def test_the_reference_is_random_not_derived(project, make_project, rate):
    e = rate()
    assert e.actor_ref.startswith("actor:") and len(e.actor_ref) == len("actor:") + 32
    for purpose in PURPOSES:                                          # no key turns the subject into it
        assert secrets.digest(project["pid"], purpose, MEMBER).split(":")[-1] not in e.actor_ref
    other = make_project(OWNER, editors=(MEMBER,))
    assert rate(pid=other["pid"]).actor_ref != e.actor_ref           # one per project


def test_the_same_person_keeps_one_reference_in_a_project(rate):
    assert rate(n=1).actor_ref == rate(n=2).actor_ref


@pytest.mark.parametrize("scope", ["project", "platform"])
def test_first_sightings_at_once_make_one_reference(project, scope):
    """Unique on (scope, sub): two requests at the same moment can't mint two, also in the platform's
    own scope, where a NULL project would not be unique (n-g, fourth review 3)."""
    import threading
    import uuid as _uuid

    newcomer = str(_uuid.uuid4())                                  # never seen: a real first sighting
    where = project["pid"] if scope == "project" else None
    refs, errors = [], []

    def run():
        try:
            refs.append(actors.ref_for(where, newcomer, "olive"))
        except Exception as exc:                                     # pragma: no cover - reported below
            errors.append(exc)
    threads = [threading.Thread(target=run) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len(set(refs)) == 1


def test_a_changed_name_in_the_mapping_is_detected(project, rate):
    """The MAC covers the reference, the subject and the name (n-g)."""
    e = rate()
    actors.tamper(project["pid"], e.actor_ref, name="mallory")
    with pytest.raises(actors.MappingAlarm):
        person(project["pid"], e.actor_ref)


def test_the_platform_scope_keeps_one_reference_per_person(project):
    """Requests outside any project use the platform's own scope: stable there, and erasable (n-g)."""
    first = actors.ref_for(None, STRANGER, "sam")
    assert actors.ref_for(None, STRANGER, "sam") == first
    actors.erase(None, STRANGER)
    assert person(None, first) is None


def test_the_key_derivation_ignores_the_case_of_the_pid(project):
    assert secrets.content_digest(project["pid"].upper(), {"a": 1}) == secrets.content_digest(project["pid"], {"a": 1})


def test_a_swapped_mapping_row_is_detected(project, rate):
    e = rate()
    actors.tamper(project["pid"], e.actor_ref, sub=OWNER)                 # test hook: someone edits the row
    with pytest.raises(actors.MappingAlarm):
        person(project["pid"], e.actor_ref)


def test_erasure_is_real(project, rate):
    e = rate()
    actors.erase(project["pid"], MEMBER)
    assert person(project["pid"], e.actor_ref) is None
    assert [x.actor_ref for x in entries_of(project["pid"]) if x.action == "risk.rated"] == [e.actor_ref]
    assert rate(n=2).actor_ref != e.actor_ref                        # a new link, unrelated to the old one


# PR5-PR6: digests are the platform's (N4) -------------------------------------------------------------

def test_the_platform_computes_the_content_digest(project, rate):
    e = rate()
    assert e.content_sha256 == secrets.content_digest(project["pid"], {"answer": "yes"})
    assert e.content_sha256.startswith("hmac:v1:")
    assert e.content_sha256.split(":")[-1] != hashlib.sha256(canonical({"answer": "yes"})).hexdigest()[:32]


def test_before_and_after_states_are_digested_by_the_platform_under_a_key_never_exported(project, rate):
    """The chain check needs only equality, and the content key goes to auditors: states use their own
    `state` key, so a rating history can't be brute-forced from an export (third review n-e)."""
    e = rate(before={"impact": 3}, after={"impact": 5})
    assert e.before_sha256 == secrets.state_digest(project["pid"], {"impact": 3})
    assert e.after_sha256 == secrets.state_digest(project["pid"], {"impact": 5})
    assert e.after_sha256 != secrets.content_digest(project["pid"], {"impact": 5})


@pytest.mark.parametrize("field", ["content_sha256", "before_sha256", "after_sha256"])
def test_an_app_sending_a_digest_is_rejected(project, rate, field):
    assert rate(**{field: "0" * 64}) is None                          # no trusted entry
    [r] = [x for x in entries_of(project["pid"]) if x.action == "ledger.rejected"]
    assert r.details["reason"] == f"platform_field:{field}"


def test_the_same_content_digests_differently_in_two_projects(project, make_project):
    other = make_project(OWNER)
    assert secrets.content_digest(project["pid"], {"a": 1}) != secrets.content_digest(other["pid"], {"a": 1})


# PR7: rotation (T22) -------------------------------------------------------------------------------

def test_after_a_rotation_new_digests_use_the_new_key_and_old_ones_still_check(project, rate, monkeypatch):
    old = rate(n=1)
    monkeypatch.setenv("PLATFORM_LEDGER_KEYS", LEDGER_KEYS + ",v2:" + "b2" * 32)
    new = rate(n=2)
    assert old.content_sha256.startswith("hmac:v1:") and new.content_sha256.startswith("hmac:v2:")
    assert secrets.check(project["pid"], "content", canonical({"answer": "yes"}), old.content_sha256)
    assert secrets.check(project["pid"], "content", canonical({"answer": "yes"}), new.content_sha256)
    assert person(project["pid"], old.actor_ref)[0] == MEMBER          # mapping rows under v1 still verify


def test_a_digest_of_a_retired_version_no_longer_checks(project, rate, monkeypatch):
    old = rate()
    monkeypatch.setenv("PLATFORM_LEDGER_KEYS", "v2:" + "b2" * 32)
    assert not secrets.check(project["pid"], "content", canonical({"answer": "yes"}), old.content_sha256)


# PR8: the auditor's key ------------------------------------------------------------------------------

def test_the_export_carries_only_this_projects_content_key(client, as_user, project, make_project, rate, tmp_path,
                                                           memory_ledger):
    rate()
    other = make_project(OWNER)
    text = client.get(f"/projects/{project['slug']}/ledger/export", headers=as_user(OWNER)).text
    head = [json.loads(line) for line in text.splitlines() if line.strip()][-1]["head"]
    keys = head["keys"]
    assert set(keys) == {"content"}
    assert keys["content"] == {v: k.hex() for v, k in secrets.derive_all(project["pid"], "content").items()}
    assert keys["content"] != {v: k.hex() for v, k in secrets.derive_all(other["pid"], "content").items()}
    assert "a1" * 32 not in text and "b2" * 32 not in text
    path, key = tmp_path / "e.jsonl", tmp_path / "pub"
    path.write_text(text)
    key.write_text(memory_ledger.public_key_pem())
    checked = subprocess.run([sys.executable, str(ROOT / "scripts/verify-ledger-export.py"), "--public-key", str(key),
                              "--check-content", str(path)], capture_output=True, text=True)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    lines = [json.loads(line) for line in text.splitlines() if line.strip()]
    target = next(line for line in lines if line.get("entry", {}).get("action") == "risk.rated")
    target["content"] = {"answer": "no"}                              # the frozen content, edited (n-i)
    path.write_text("\n".join(json.dumps(line) for line in lines))
    tampered = subprocess.run([sys.executable, str(ROOT / "scripts/verify-ledger-export.py"), "--public-key",
                               str(key), "--check-content", str(path)], capture_output=True, text=True)
    assert tampered.returncode != 0


# S8 (decided 2026-10-02): the person mapping is beyond the inspector --------------------------------

def test_the_person_mapping_lives_where_the_inspector_cannot_connect():
    """pgAdmin's role reads everything it can connect to (pg_read_all_data), so the only table naming
    people is in its own database, closed to PUBLIC, the inspector and every module role."""
    import psycopg
    from psycopg.conninfo import make_conninfo

    from tests.ledger.conftest import SUPERUSER_DSN, need

    need(SUPERUSER_DSN, "PLATFORM_TEST_SUPERUSER_URL is not set")
    with psycopg.connect(SUPERUSER_DSN) as conn:
        assert conn.execute("SELECT 1 FROM pg_database WHERE datname = 'ledger_identity'").fetchone(), \
            "the ledger_identity database is missing"
        for role in ("inspector_ro", "report_ro", "qualification_rw", "controls_rw", "control_objectives_rw",
                     "report_composer_rw", "engine_rw", "dashboard_ro"):
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
            if exists:
                assert not conn.execute("SELECT has_database_privilege(%s, 'ledger_identity', 'CONNECT')",
                                        (role,)).fetchone()[0], f"{role} may connect to ledger_identity"
        assert conn.execute("SELECT has_database_privilege('platform_rw', 'ledger_identity', 'CONNECT')").fetchone()[0]
    with psycopg.connect(make_conninfo(SUPERUSER_DSN, dbname="platform")) as conn:
        assert not conn.execute("SELECT to_regclass('ledger.actor')").fetchone()[0], \
            "the mapping must not be in the platform database, where the inspector reads"
