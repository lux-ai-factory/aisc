"""The verifier and the reconciliation (spec 7.3, 7.4; I4, I11, R2.6, R2.10).

`verify(pid)` reads a project's log back, verified, and reports what reconciliation looks for:
- entries that don't verify;
- item chain breaks (an accepted event whose `before` isn't the previous event's `after`);
- action ids used outside their first request's actions;
- witnessed writes with no event after the window;
- a database the pool assigned that the store no longer has.

Evidence checks (the frozen content against the evidence store) and changes made outside the apps
come with phase 10; their counts stay 0 until then.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from platform_service.ledger import settings
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
            after = page[-1].seq
    with db.pool().connection() as conn:
        rows = conn.execute(
            "SELECT item_type, item_id, before_sha256, after_sha256 FROM ledger.event_index WHERE log = %s"
            " AND reason IS NULL AND item_id IS NOT NULL AND action NOT LIKE 'request.%%'"
            " AND (before_sha256 IS NOT NULL OR after_sha256 IS NOT NULL) ORDER BY seq", (log,)).fetchall()
        last: dict = {}
        for r in rows:
            key = (r["item_type"], r["item_id"])
            if key in last and r["before_sha256"] is not None and r["before_sha256"] != last[key]:
                report.chain_breaks += 1
            if r["after_sha256"] is not None:
                last[key] = r["after_sha256"]
        report.action_id_conflicts = conn.execute(
            "SELECT count(*) AS n FROM ledger.event_index WHERE log = %s AND reason = 'action_id'",
            (log,)).fetchone()["n"]
        cutoff = datetime.now(timezone.utc) - settings.WINDOW
        report.witness_without_event = conn.execute(
            "SELECT count(*) AS n FROM ledger.witness w WHERE w.project_pid = %s AND w.at < %s"
            " AND w.method NOT IN ('GET', 'HEAD', 'OPTIONS') AND NOT EXISTS (SELECT 1 FROM ledger.event_index i"
            "  WHERE i.log = %s AND i.request_id = w.request_id AND i.action NOT LIKE 'request.%%')",
            (pid, cutoff, log)).fetchone()["n"]
    return report
