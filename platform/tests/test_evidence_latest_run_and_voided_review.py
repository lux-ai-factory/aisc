"""Step 4's evidence map tells the truth about a test's latest state and about a review a later change ended.

A test whose early runs failed (a setup error) and whose later runs are Done is evidence, not "attention";
attention stays for a test whose latest run failed. A change of links or notes on a reviewed map does not erase
who reviewed it: the review stays on record, ended, and the ledger's links-saved event names the review it ended.

Reuses the project of test_evidence.py: its latest card version V2 selects O1 and O24, LangBiTe covers O1.
"""
from __future__ import annotations

import pytest

from tests.conftest import needs_database
from tests.test_evidence import (BOB, LB, V2, _reader, _runs, catalogue, evidence_project, get, put,  # noqa: F401
                                 sql, tools)

pytestmark = needs_database


def objective(body, oid):
    return next(o for o in body["objectives"] if o["id"] == oid)


def review(client, as_user, project, who=BOB):
    return client.post(f"/projects/{project['slug']}/evidence/review", json={"version": None},
                       headers=as_user(who))


# ── a test's state is its latest run's ─────────────────────────────────────

def test_failed_setup_runs_followed_by_done_runs_are_evidence(client, as_user, evidence_project, dsn):  # noqa: F811
    put(client, as_user, evidence_project, [LB])
    pid = evidence_project["pid"]
    _runs(dsn, pid, "aisc-plugin-langbite", V2, "Failed", "Failed", when="2026-11-01T09:00:00+00:00")
    _runs(dsn, pid, "aisc-plugin-langbite", V2, "Done", "Done", when="2026-11-02T09:00:00+00:00")
    got = objective(get(client, as_user, evidence_project).json(), "O1")["evidence"]
    assert got == "evidence", f"the test's later runs are Done, yet the map says {got!r}"


def test_a_failed_latest_run_still_asks_for_attention(client, as_user, evidence_project, dsn):  # noqa: F811
    put(client, as_user, evidence_project, [LB])
    pid = evidence_project["pid"]
    _runs(dsn, pid, "aisc-plugin-langbite", V2, "Done", when="2026-11-01T09:00:00+00:00")
    _runs(dsn, pid, "aisc-plugin-langbite", V2, "Failed", when="2026-11-02T09:00:00+00:00")
    assert objective(get(client, as_user, evidence_project).json(), "O1")["evidence"] == "attention"


# ── a change of links ends a review without erasing it ─────────────────────

def test_a_change_of_links_keeps_the_ended_review_on_record(client, as_user, evidence_project, dsn):  # noqa: F811
    put(client, as_user, evidence_project, [LB])
    assert review(client, as_user, evidence_project).status_code == 200
    put(client, as_user, evidence_project, [{**LB, "note": "a new reason"}])
    assert get(client, as_user, evidence_project).json()["review"] is None        # the review no longer holds
    kept = sql(dsn, evidence_project["pid"], "SELECT reviewed_by FROM evidence.review WHERE system_id::text = %s",
               (V2,))
    assert [r[0] for r in kept] == [BOB], f"who reviewed the map before the change is gone: {kept}"


def test_the_links_saved_event_names_the_review_it_ended(client, as_user, evidence_project, monkeypatch):  # noqa: F811
    from tests.ledger.test_ledger_outbox import SUPERUSER_DSN, as_superuser

    if not SUPERUSER_DSN:
        pytest.skip("PLATFORM_TEST_SUPERUSER_URL is not set: ledger.outbox is read as the superuser")
    monkeypatch.setenv("LEDGER_MODE", "record")
    put(client, as_user, evidence_project, [LB])
    review(client, as_user, evidence_project)
    put(client, as_user, evidence_project, [{**LB, "note": "a new reason"}])
    rows = as_superuser(evidence_project["pid"], "SELECT details FROM ledger.outbox"
                                                 " WHERE action = 'evidence.links.saved' ORDER BY occurred_at")
    last = rows[-1][0]
    assert last.get("review_voided") == BOB, f"the save that ended Bob's review does not say so: {last}"


def test_a_save_on_a_map_nobody_reviewed_names_no_ended_review(client, as_user, evidence_project, monkeypatch):  # noqa: F811
    from tests.ledger.test_ledger_outbox import SUPERUSER_DSN, as_superuser

    if not SUPERUSER_DSN:
        pytest.skip("PLATFORM_TEST_SUPERUSER_URL is not set: ledger.outbox is read as the superuser")
    monkeypatch.setenv("LEDGER_MODE", "record")
    put(client, as_user, evidence_project, [LB])
    rows = as_superuser(evidence_project["pid"], "SELECT details FROM ledger.outbox"
                                                 " WHERE action = 'evidence.links.saved' ORDER BY occurred_at")
    assert "review_voided" not in rows[-1][0]
