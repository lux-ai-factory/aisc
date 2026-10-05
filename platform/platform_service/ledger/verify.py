"""The verifier and the reconciliation.

`verify(pid)` reads a project's log back, verified, and reports what reconciliation looks for:
- entries that don't verify;
- item chain breaks (an accepted event whose `before` isn't the previous event's `after`);
- action ids used outside their first request's actions;
- witnessed writes with no event after the window;
- a database the pool assigned that the store no longer has.

Evidence checks (the frozen content against the evidence store) and changes made outside the apps
are not implemented yet; their counts stay 0.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from platform_service.ledger import settings
from platform_service.ledger.canonical import canonical
from platform_service.ledger.store import LedgerError, TamperAlarm


@dataclass
class Report:
    entries_ok: int = 0
    entries_failed: int = 0
    chain_breaks: int = 0
    action_id_conflicts: int = 0
    evidence_ok: int = 0
    evidence_failed: int = 0
    witness_without_event: int = 0
    outside_changes: int = 0
    missing_database: bool = False
    #: index rows that say something else than their entry (an edited filter column hides a row)
    index_mismatches: int = 0
    #: entries of the log with no index row, and index rows with no entry
    index_missing: int = 0
    #: AI runs started longer than RUN_WINDOW ago with no end (a killed agent, or a mapping whose
    #: process died before its save)
    open_runs: int = 0


def verify(pid: str) -> Report:
    from platform_service import db, ledger
    from platform_service.ledger import provision

    report = Report()
    log = provision.database_for(pid)
    if log is None:
        return report
    store = ledger.current()
    try:
        report.missing_database = log not in store.databases()
    except LedgerError:
        report.missing_database = True
    logged = {}
    if not report.missing_database:
        after = 0
        while True:
            try:
                page = store.scan(log, after_seq=after, limit=500)
            except TamperAlarm:
                report.entries_failed += 1
                break
            if not page:
                break
            report.entries_ok += len(page)
            logged.update((e.seq, e.as_dict()) for e in page)
            after = page[-1].seq
    with db.pool().connection() as conn:
        if logged:
            from platform_service.ledger import index

            indexed = {r["seq"]: r for r in conn.execute("SELECT * FROM ledger.event_index WHERE log = %s", (log,))}
            report.index_missing = len(set(logged) ^ set(indexed))
            report.index_mismatches = sum(1 for seq in set(logged) & set(indexed)
                                          if not index.agrees(indexed[seq], logged[seq]))
        rows = conn.execute(
            "SELECT event_id, item_type, item_id, before_sha256, after_sha256 FROM ledger.event_index WHERE log = %s"
            " AND reason IS NULL AND item_id IS NOT NULL AND action NOT LIKE 'request.%%'"
            " AND (before_sha256 IS NOT NULL OR after_sha256 IS NOT NULL) ORDER BY seq", (log,)).fetchall()
        states = {r["event_id"]: r for r in conn.execute(
            "SELECT event_id, before, after FROM ledger.content WHERE log = %s", (log,))}
        last: dict = {}
        for r in rows:
            key = (r["item_type"], r["item_id"])
            if key in last and r["before_sha256"] is not None and _differs(last[key], r, states):
                report.chain_breaks += 1
            if r["after_sha256"] is not None:
                last[key] = r
        report.action_id_conflicts = conn.execute(
            "SELECT count(*) AS n FROM ledger.event_index WHERE log = %s AND reason = 'action_id'",
            (log,)).fetchone()["n"]
        report.open_runs = conn.execute(
            "SELECT count(*) AS n FROM ledger.event_index s WHERE s.log = %s"
            " AND s.action IN ('agent.run_started', 'card.ai_refinement_requested', 'ai.mapping.requested')"
            " AND s.reason IS NULL AND s.occurred_at < %s AND NOT EXISTS (SELECT 1 FROM ledger.event_index e"
            "  WHERE e.log = s.log AND e.run_id = s.run_id AND e.reason IS NULL"
            "  AND e.action IN ('agent.run_finished', 'agent.run_failed', 'ai.mapping.completed',"
            "                   'ai.mapping.failed'))",
            (log, datetime.now(timezone.utc) - settings.RUN_WINDOW)).fetchone()["n"]
        cutoff = datetime.now(timezone.utc) - settings.WINDOW
        report.witness_without_event = conn.execute(
            "SELECT count(*) AS n FROM ledger.witness w WHERE w.project_pid = %s AND w.at < %s"
            " AND w.method NOT IN ('GET', 'HEAD', 'OPTIONS') AND NOT EXISTS (SELECT 1 FROM ledger.event_index i"
            "  WHERE i.log = %s AND i.request_id = w.request_id AND i.action NOT LIKE 'request.%%')",
            (pid, cutoff, log)).fetchone()["n"]
    return report


def _version(digest: str | None) -> str | None:
    return digest.split(":")[1] if digest and digest.count(":") == 2 else None


def _differs(previous: dict, current: dict, states: dict) -> bool:
    """Whether an event's `before` is not its item's previous `after`. Digests under one key version are
    compared as they are; across a key rotation they can't be, so the frozen states are compared instead,
    and a pair with no frozen state is not counted as a break."""
    if _version(previous["after_sha256"]) == _version(current["before_sha256"]):
        return previous["after_sha256"] != current["before_sha256"]
    was, now = states.get(previous["event_id"]), states.get(current["event_id"])
    if was is None or now is None or was["after"] is None or now["before"] is None:
        return False
    return canonical(was["after"]) != canonical(now["before"])
