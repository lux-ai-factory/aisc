"""A1-A4: reading the ledger (I4, I9, T12, T21; spec 6.3). Members list and filter their project's
ledger from the index, and every entry is verified against immudb before it is shown. An index row
that disagrees is an alarm. The export carries each entry's inclusion proof and the server-signed
state, so the offline checker verifies against the signing key, not against the file's own claims
(R4.9). Strangers get 404."""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg

from platform_service.ledger import testing
from tests.conftest import DSN
from tests.ledger.conftest import log_of, needs_db, MEMBER, OWNER, STRANGER

pytestmark = needs_db
ROOT = Path(__file__).resolve().parents[3]
CHECKER = ROOT / "scripts" / "verify-ledger-export.py"


def seed(pid, n=3, **over):
    """Entries written the way the relay writes them: to immudb and to the read index, `actor_sub`
    turned into its `actor_ref` and mapping (I10)."""
    events = []
    for i in range(n):
        e = {"event_id": str(uuid.uuid4()), "action": "risk.rated", "item_type": "risk", "item_id": f"risk{i}",
             "actor_kind": "user", "actor_sub": OWNER if i % 2 == 0 else MEMBER, "source_app": "control_objectives",
             "step": 2, "details": {}}
        e.update(over)
        events.append(e)
    return testing.seed(pid, events)                                 # -> seqs


def test_a_member_lists_the_projects_entries_newest_first(client, as_user, project, memory_ledger):
    seqs = seed(project["pid"])
    r = client.get(f"/projects/{project['slug']}/ledger/events", headers=as_user(MEMBER))
    assert r.status_code == 200, r.text
    assert [e["seq"] for e in r.json()["events"]] == sorted(seqs, reverse=True)


def test_a_stranger_gets_404(client, as_user, project, memory_ledger):
    seed(project["pid"])
    assert client.get(f"/projects/{project['slug']}/ledger/events", headers=as_user(STRANGER)).status_code == 404


def test_filters_narrow_the_list(client, as_user, project, memory_ledger):
    seed(project["pid"], n=4)
    r = client.get(f"/projects/{project['slug']}/ledger/events?actor={OWNER}&step=2", headers=as_user(MEMBER))
    events = r.json()["events"]
    assert events and {e["actor"]["sub"] for e in events} == {OWNER}


def test_another_projects_entries_never_appear(client, as_user, make_project, project, memory_ledger):
    other = make_project(MEMBER)
    seed(other["pid"], n=2)
    r = client.get(f"/projects/{project['slug']}/ledger/events", headers=as_user(MEMBER))
    assert r.json()["events"] == []


def test_an_entry_is_shown_verified(client, as_user, project, memory_ledger):
    [seq] = seed(project["pid"], n=1)
    r = client.get(f"/projects/{project['slug']}/ledger/events/{seq}", headers=as_user(MEMBER))
    assert r.status_code == 200 and r.json()["verified"] is True


def test_a_tampered_entry_is_an_alarm_not_a_page(client, as_user, project, memory_ledger):

    [seq] = seed(project["pid"], n=1)
    memory_ledger.tamper(log_of(project["pid"]), seq, "item_id", "risk9")
    r = client.get(f"/projects/{project['slug']}/ledger/events/{seq}", headers=as_user(MEMBER))
    assert r.status_code == 409 and "tamper" in r.text.lower()


def test_an_index_row_that_disagrees_with_immudb_is_an_alarm(client, as_user, project, memory_ledger):
    [seq] = seed(project["pid"], n=1)
    with psycopg.connect(DSN) as conn:                               # someone edits the read index
        conn.execute("UPDATE ledger.event_index SET item_id = 'risk9' WHERE project_pid = %s AND seq = %s",
                     (project["pid"], seq))
    r = client.get(f"/projects/{project['slug']}/ledger/events", headers=as_user(MEMBER))
    assert r.status_code == 409 and "index" in r.text.lower()


def _export(client, as_user, project):
    r = client.get(f"/projects/{project['slug']}/ledger/export", headers=as_user(OWNER))
    assert r.status_code == 200, r.text
    return r.text


def _check(path, key_path):
    return subprocess.run([sys.executable, str(CHECKER), "--public-key", str(key_path), str(path)],
                          capture_output=True, text=True)


def test_the_export_is_for_the_export_roles_only(client, as_user, project, memory_ledger, settings):
    seed(project["pid"], n=1)
    expected = 200 if "editor" in settings.EXPORT_ROLES else 403
    assert client.get(f"/projects/{project['slug']}/ledger/export", headers=as_user(MEMBER)).status_code == expected


def test_the_export_checks_offline_against_the_signing_key(client, as_user, project, memory_ledger, tmp_path):
    seed(project["pid"], n=3)
    text = _export(client, as_user, project)
    lines = [json.loads(line) for line in text.splitlines() if line.strip()]
    assert all("proof" in line for line in lines[:-1]) and "signature" in lines[-1]["head"]
    key = tmp_path / "immudb.pub"
    key.write_text(memory_ledger.public_key_pem())
    path = tmp_path / "export.jsonl"
    path.write_text(text)
    assert _check(path, key).returncode == 0


def test_an_edited_export_fails_even_with_its_hashes_recomputed(client, as_user, project, memory_ledger, tmp_path):
    """Recomputing every hash after an edit isn't enough: the signed state no longer matches."""
    seed(project["pid"], n=3)
    lines = [json.loads(line) for line in _export(client, as_user, project).splitlines() if line.strip()]
    lines[1]["entry"]["item_id"] = "risk9"
    forged = testing.rehash_export(lines)                            # test helper: an attacker's best effort
    key = tmp_path / "immudb.pub"
    key.write_text(memory_ledger.public_key_pem())
    path = tmp_path / "forged.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in forged))
    assert _check(path, key).returncode != 0


def test_only_an_admin_sees_every_projects_head(client, as_user, project, memory_ledger):
    seed(project["pid"], n=1)
    assert client.get("/ledger/projects", headers=as_user(OWNER)).status_code == 403
    r = client.get("/ledger/projects", headers=as_user("admin-sub", roles=("primary-user", "admin")))
    assert r.status_code == 200 and project["pid"] in {p["pid"] for p in r.json()["projects"]}


def test_only_an_admin_can_reanchor_and_it_is_recorded(client, as_user, project, memory_ledger):
    from platform_service.ledger.naming import PLATFORM_DB

    seed(project["pid"], n=1)
    assert client.post("/ledger/reanchor", json={"pid": project["pid"]}, headers=as_user(OWNER)).status_code == 403
    r = client.post("/ledger/reanchor", json={"pid": project["pid"]},
                    headers=as_user("admin-sub", roles=("primary-user", "admin")))
    assert r.status_code == 200
    [e] = [x for x in memory_ledger.scan(PLATFORM_DB, after_seq=0, limit=100) if x.action == "ledger.reanchored"]
    assert {"old_head", "new_head"} <= set(e.details)


def test_a_project_on_immudb_exports_a_file_the_checker_accepts(client, as_user, immudb_ledger, make_project, tmp_path):
    """S9: the export route on the real store: immudb's transactions and signed state, checked offline."""
    import os

    from tests.ledger.conftest import need

    key_path = os.environ.get("LEDGER_TEST_IMMUDB_PUBLIC_KEY")
    need(key_path, "LEDGER_TEST_IMMUDB_PUBLIC_KEY is not set")
    on_immudb = make_project(OWNER, editors=(MEMBER,))
    seed(on_immudb["pid"], n=3)
    text = _export(client, as_user, on_immudb)
    assert json.loads(text.splitlines()[-1])["head"]["format"] == "immudb"
    path = tmp_path / "export.jsonl"
    path.write_text(text)
    checked = subprocess.run([sys.executable, str(CHECKER), "--public-key", key_path, "--check-content", str(path)],
                             capture_output=True, text=True)
    assert checked.returncode == 0, checked.stdout + checked.stderr
