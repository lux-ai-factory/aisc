"""Resend the test installs the ledger refused because they cited no request.

Before the platform passed the person's request id on to the engine, a test installed with the catalogue's
Install button reached the ledger as an engine `plugin.installed` event with no request, and the relay refused
it (`missing_request`). The witness did record the person's catalogue install request, a moment before. This
command pairs each refused install with that request:

- the witness row is the platform's POST to the catalogue install route of the same project;
- it was recorded at most `settings.WINDOW` before the refused event, and is the latest such row;
- no accepted `plugin.installed` cites it, and no other pair of this run takes it.

Without `--yes` it lists the pairs (package, version, times; never who) and writes nothing. With `--yes` it
queues, for each pair, a new event: the original's time, item and details, plus `resends` (the refused event's
id), citing the witnessed request. The relay then judges it as any other event. A refused install with no such
request is listed with the reason and skipped; one already resent is not listed again.

    python -m platform_service.ledger.resend_refused_installs [--yes]
"""
from __future__ import annotations

import argparse
import re
import sys
import uuid

from platform_service.ledger import settings

#: The catalogue's Install route, as the witness records its path.
CATALOGUE_INSTALL = re.compile(r"^/api/projects/[^/]+/catalogue/api/tool/[^/]+/install$")


def _refused(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT o.* FROM core.outbox o WHERE o.action = 'plugin.installed' AND o.delivered_reason = 'missing_request'"
        " AND NOT EXISTS (SELECT 1 FROM core.outbox r WHERE r.action = 'plugin.installed'"
        " AND r.details->>'resends' = o.event_id::text)"
        " ORDER BY o.occurred_at, o.event_id").fetchall()]


def _candidates(conn, row: dict) -> list[dict]:
    """The platform's POST requests of the row's project in the window before it, latest first."""
    rows = conn.execute(
        "SELECT w.request_id, w.route_path, w.at FROM ledger.witness w"
        " WHERE w.app = 'platform' AND w.method = 'POST' AND w.project_pid = %s"
        " AND w.at BETWEEN %s AND %s"
        " AND NOT EXISTS (SELECT 1 FROM ledger.event_index e WHERE e.request_id = w.request_id"
        " AND e.action = 'plugin.installed' AND e.reason IS NULL)"
        " ORDER BY w.at DESC, w.request_id",
        (row["project_pid"], row["occurred_at"] - settings.WINDOW, row["occurred_at"])).fetchall()
    return [dict(r) for r in rows if CATALOGUE_INSTALL.match(r["route_path"])]


def pairs(conn) -> list[dict]:
    """Each refused install with the request it came from, or None and why."""
    taken: set[str] = set()
    out = []
    for row in _refused(conn):
        details = row["details"] or {}
        pair = {"event_id": str(row["event_id"]), "project_pid": str(row["project_pid"]) if row["project_pid"] else None,
                "package": details.get("package"), "version": details.get("version"),
                "occurred_at": row["occurred_at"], "request_id": None, "why_none": None}
        if row["project_pid"] is None:
            pair["why_none"] = "the event names no project"
        else:
            found = next((c for c in _candidates(conn, row) if str(c["request_id"]) not in taken), None)
            if found is None:
                pair["why_none"] = "no catalogue install request of this project in the minutes before it"
            else:
                pair["request_id"] = str(found["request_id"])
                pair["requested_at"] = found["at"]
                taken.add(pair["request_id"])
        out.append(pair)
    return out


def resend(conn, found: list[dict]) -> int:
    """Queue a new event for each pair that has a request, on `conn` (the caller commits). Returns how many."""
    from platform_service.ledger import outbox

    sent = 0
    for pair in found:
        if not pair.get("request_id"):
            continue
        row = conn.execute("SELECT * FROM core.outbox WHERE event_id = %s", (pair["event_id"],)).fetchone()
        details = {**(row["details"] or {}), "resends": str(row["event_id"])}
        queued = outbox.emit(conn, row["action"], project_pid=row["project_pid"], item_type=row["item_type"],
                             item_id=row["item_id"], details=details, content=row["content"], before=row["before"],
                             after=row["after"], item_version=row["item_version"], card_version=row["card_version"],
                             request_id=pair["request_id"], emitter=row["emitter"], event_id=str(uuid.uuid4()),
                             occurred_at=row["occurred_at"])
        sent += queued is not None
    return sent


def _print(found: list[dict]) -> None:
    for p in found:
        what = f"{p['package']} {p['version']} at {p['occurred_at'].isoformat()} (event {p['event_id']})"
        if p["request_id"]:
            print(f"pair: {what} <- request {p['request_id']} at {p['requested_at'].isoformat()}")
        else:
            print(f"skip: {what}: {p['why_none']}")
    matched = sum(1 for p in found if p["request_id"])
    print(f"total: {len(found)} refused, {matched} paired, {len(found) - matched} skipped")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m platform_service.ledger.resend_refused_installs",
                                     description="Pair the test installs the ledger refused for want of a request "
                                                 "with the catalogue install request each came from, and resend them.")
    parser.add_argument("--yes", action="store_true", help="queue the resends; without it nothing is written")
    args = parser.parse_args(argv)
    from platform_service import db

    with db.pool().connection() as conn:
        found = pairs(conn)
        _print(found)
        if not args.yes:
            print("nothing written: run again with --yes to resend the paired ones")
            return 0
        with conn.transaction():
            sent = resend(conn, found)
    print(f"queued: {sent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
