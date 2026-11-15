"""Installs made through the platform's catalogue are accepted, and the ones refused before can be resent.

The engine's plugin.installed is caused by the platform's catalogue install route too. Before that, the
platform did not forward the person's request id to the engine, so those events reached the ledger with no
request and were refused (missing_request). `python -m platform_service.ledger.resend_refused_installs`
pairs each refused one with the catalogue install request the witness recorded just before it, lists the
pairs, and with --yes queues a new event citing that request and naming the original.
"""
from __future__ import annotations

import uuid

import psycopg
import pytest

from tests.conftest import DSN
from tests.ledger.conftest import ADMIN, ADMIN_ROLES, entries, log_of, needs_db, relay_all

pytestmark = needs_db
TOKEN = "engine-token-0123456789"


@pytest.fixture(autouse=True)
def _enforce(mode, monkeypatch):
    mode("enforce")
    monkeypatch.setenv("PLATFORM_LEDGER_ENGINE_TOKEN", TOKEN)


def command():
    try:
        from platform_service.ledger import resend_refused_installs
    except ImportError:
        pytest.fail("there is no command that resends the refused installs (platform_service.ledger."
                    "resend_refused_installs)")
    return resend_refused_installs


def catalogue_install(witnessed, project, entry="demo"):
    return witnessed(ADMIN, "POST", "platform", f"/api/projects/{project['slug']}/catalogue/api/tool/{entry}/install",
                     roles=ADMIN_ROLES)


def send_install(client, project, request_id, package="aisc-plugin-demo", version="1.0.0"):
    event_id = str(uuid.uuid4())
    r = client.post(f"/internal/projects/{project['pid']}/ledger/events",
                    json={"event_id": event_id, "request_id": request_id, "action": "plugin.installed",
                          "item_type": "plugin", "item_id": package,
                          "details": {"package": package, "version": version, "reused": False}},
                    headers={"X-AISC-Service-Token": TOKEN})
    assert r.status_code == 202, r.text
    return event_id


def rejected(store, pid):
    return [e.details["reason"] for e in entries(store, log_of(pid)) if e.action == "ledger.rejected"]


def refused_install(client, witnessed, project, **kw):
    """A catalogue install the witness saw, whose engine event carried no request id."""
    request_id = catalogue_install(witnessed, project)
    event_id = send_install(client, project, None, **kw)
    relay_all(project["pid"])
    return request_id, event_id


def test_an_install_through_the_platform_is_accepted_by_the_relay(client, project, memory_ledger, witnessed):
    request_id = catalogue_install(witnessed, project)
    send_install(client, project, request_id)
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == [], "a catalogue install's engine event was refused"
    assert [e.request_id for e in entries(memory_ledger, log_of(project["pid"]))
            if e.action == "plugin.installed"] == [request_id]


def test_resend_pairs_each_refused_install_with_its_request(client, project, memory_ledger, witnessed):
    first = refused_install(client, witnessed, project, package="aisc-plugin-a")
    second = refused_install(client, witnessed, project, package="aisc-plugin-b")
    assert rejected(memory_ledger, project["pid"]) == ["missing_request", "missing_request"]
    resend = command()
    with psycopg.connect(DSN, row_factory=psycopg.rows.dict_row) as conn:
        pairs = {p["event_id"]: p["request_id"] for p in resend.pairs(conn)}
    assert pairs.get(first[1]) == first[0] and pairs.get(second[1]) == second[0]


def test_resend_without_yes_writes_nothing(client, project, memory_ledger, witnessed, capsys):
    refused_install(client, witnessed, project)
    resend = command()
    with psycopg.connect(DSN) as conn:
        before = conn.execute("SELECT count(*) FROM core.outbox").fetchone()[0]
    resend.main([])
    with psycopg.connect(DSN) as conn:
        after = conn.execute("SELECT count(*) FROM core.outbox").fetchone()[0]
    assert after == before
    assert "aisc-plugin-demo" in capsys.readouterr().out


def test_resent_installs_are_accepted_and_name_the_original(client, project, memory_ledger, witnessed):
    request_id, original = refused_install(client, witnessed, project)
    resend = command()
    with psycopg.connect(DSN, row_factory=psycopg.rows.dict_row) as conn:
        assert resend.resend(conn, [p for p in resend.pairs(conn) if p["project_pid"] == project["pid"]]) == 1
        conn.commit()
    relay_all(project["pid"])
    [again] = [e for e in entries(memory_ledger, log_of(project["pid"])) if e.action == "plugin.installed"]
    assert again.request_id == request_id and again.details["resends"] == original


def test_a_refused_install_with_no_witness_is_skipped(client, project, memory_ledger, witnessed):
    send_install(client, project, None)
    relay_all(project["pid"])
    resend = command()
    with psycopg.connect(DSN, row_factory=psycopg.rows.dict_row) as conn:
        [pair] = [p for p in resend.pairs(conn) if p["project_pid"] == project["pid"]]
    assert pair["request_id"] is None and pair["why_none"]
