"""A1-A3: reading the ledger (I4, I9, T12). Members read and filter their project's ledger; strangers
get 404; every entry shown was read back verified; the export is checked offline by the shipped script."""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from platform_service.ledger.naming import database_name
from tests.conftest import needs_database
from tests.ledger.conftest import MEMBER, OWNER, STRANGER

pytestmark = needs_database
ROOT = Path(__file__).resolve().parents[3]


def seed(store, pid, n=3, **over):
    db = database_name(pid)
    store.ensure(db)
    seqs = []
    for i in range(n):
        e = {"event_id": str(uuid.uuid4()), "action": "risk.rated", "item_type": "risk", "item_id": f"risk{i}",
             "actor_kind": "user", "actor_sub": OWNER if i % 2 == 0 else MEMBER, "actor_name": "x",
             "source_app": "control_objectives", "step": 2, "details": {"impact": 3}}
        e.update(over)
        seqs.append(store.append(db, e))
    return seqs


def test_a_member_lists_the_projects_entries_newest_first(client, as_user, project, memory_ledger):
    seqs = seed(memory_ledger, project["pid"])
    r = client.get(f"/projects/{project['slug']}/ledger/events", headers=as_user(MEMBER))
    assert r.status_code == 200, r.text
    assert [e["seq"] for e in r.json()["events"]] == sorted(seqs, reverse=True)


def test_a_stranger_gets_404(client, as_user, project, memory_ledger):
    seed(memory_ledger, project["pid"])
    assert client.get(f"/projects/{project['slug']}/ledger/events", headers=as_user(STRANGER)).status_code == 404


def test_filters_narrow_the_list(client, as_user, project, memory_ledger):
    seed(memory_ledger, project["pid"], n=4)
    r = client.get(f"/projects/{project['slug']}/ledger/events?actor={OWNER}&step=2", headers=as_user(MEMBER))
    assert {e["actor_sub"] for e in r.json()["events"]} == {OWNER}


def test_another_projects_entries_never_appear(client, as_user, unique, project, memory_ledger):
    other = client.post("/projects", json={"name": unique("other")}, headers=as_user(MEMBER)).json()
    seed(memory_ledger, other["pid"], n=2)
    r = client.get(f"/projects/{project['slug']}/ledger/events", headers=as_user(MEMBER))
    assert r.json()["events"] == []


def test_an_entry_is_shown_verified(client, as_user, project, memory_ledger):
    [seq] = seed(memory_ledger, project["pid"], n=1)
    r = client.get(f"/projects/{project['slug']}/ledger/events/{seq}", headers=as_user(MEMBER))
    assert r.status_code == 200 and r.json()["verified"] is True


def test_a_tampered_entry_is_an_alarm_not_a_page(client, as_user, project, memory_ledger):
    [seq] = seed(memory_ledger, project["pid"], n=1)
    memory_ledger.tamper(database_name(project["pid"]), seq, "actor_sub", "mallory")
    r = client.get(f"/projects/{project['slug']}/ledger/events/{seq}", headers=as_user(MEMBER))
    assert r.status_code == 409 and "tamper" in r.text.lower()


def test_the_export_is_owner_only_and_checks_offline(client, as_user, project, memory_ledger, tmp_path):
    seed(memory_ledger, project["pid"], n=3)
    assert client.get(f"/projects/{project['slug']}/ledger/export", headers=as_user(MEMBER)).status_code == 403
    r = client.get(f"/projects/{project['slug']}/ledger/export", headers=as_user(OWNER))
    assert r.status_code == 200
    lines = [json.loads(line) for line in r.text.splitlines() if line.strip()]
    assert lines[-1]["head"]["seq"] == max(line["seq"] for line in lines[:-1])
    path = tmp_path / "export.jsonl"
    path.write_text(r.text)
    checked = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify-ledger-export.py"), str(path)],
                             capture_output=True, text=True)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    broken = r.text.replace('"risk1"', '"risk9"')
    path.write_text(broken)
    assert subprocess.run([sys.executable, str(ROOT / "scripts" / "verify-ledger-export.py"), str(path)],
                          capture_output=True, text=True).returncode != 0


def test_only_an_admin_sees_every_projects_head(client, as_user, project, memory_ledger):
    seed(memory_ledger, project["pid"], n=1)
    assert client.get("/ledger/projects", headers=as_user(OWNER)).status_code == 403
    r = client.get("/ledger/projects", headers=as_user("admin-sub", roles=("primary-user", "admin")))
    assert r.status_code == 200 and project["pid"] in {p["pid"] for p in r.json()["projects"]}
