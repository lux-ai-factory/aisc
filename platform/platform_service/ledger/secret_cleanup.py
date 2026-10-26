"""Old plaintext plugin secrets out of the platform's copies of the engine's configuration events.

Before the engine masked a configuration's secrets at save, its `engine.plugin.configured` events carried them,
and the platform kept two copies: the `core.outbox` row and, once the relay accepted the event, the frozen
`ledger.content` row (the log itself holds only a keyed digest). This module, per project:

1. masks the `core.outbox` rows (config passed through `masked_for_ledger`), delivered or not, so an undelivered
   one is frozen masked;
2. redacts each frozen content still holding a plaintext secret: the content goes, the row keeps when and why
   (`redacted_at`, `redaction`), and a `ledger.content.redacted` entry in the project's own log names the
   redacted event ids with the reason, so an export marks those lines and still checks offline.

The redaction entry is appended directly, as `ledger.rejected` is (the relay would reject an outbox row with no
request), under the log's relay lock. Its id is derived from (log, reason, event ids), so a run stopped between
the append and the update finishes on the next run with the same entry. The project databases' own
`ledger.outbox` rows are only scanned for secret shapes and counted, never changed.

A project the ledger cannot take now (unavailable, or refusing an entry) is reported and the next one goes on
(exit 5). An integrity alarm stops the whole run at once, with its own message and exit code 6: nothing more is
appended or redacted in any project until the log is checked.

`count` reports what `apply` would do and writes nothing. Output names projects, items, fields and counts only,
never a value. Run by scripts/clean-old-secrets.sh, which backs the tables up first:

    python -m platform_service.ledger.secret_cleanup count [--project PID ...]
    python -m platform_service.ledger.secret_cleanup apply [--project PID ...] [--reason TEXT]
    python -m platform_service.ledger.secret_cleanup export PID
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from platform_service.ledger.config_secrets import (SECRET_SHAPE, holds_plaintext_secret, masked_for_ledger,
                                                    plaintext_secret_paths)

ACTION = "ledger.content.redacted"
REASON = "a plaintext secret in a plugin configuration"
PROGRAM = "secret-cleanup"
CONFIGURED = "engine.plugin.configured"
#: Event ids per redaction entry: keeps the entry under the store's 64 KiB cap.
CHUNK = 500
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "aisc:ledger.content.redacted")
LEDGER_DOWN = "the ledger is unavailable; nothing redacted in this project"
LEDGER_ALARM = ("the ledger raised an integrity alarm; the cleanup stopped here and redacts nothing more until the "
                "log is checked")
#: The exit code of a run stopped by an integrity alarm (5 is a project the ledger could not take).
ALARM_EXIT = 6


class SecretCleanupError(Exception):
    """The log disagrees with what this cleanup would write."""


@dataclass
class ProjectCounts:
    pid: str
    outbox_rows: int = 0        # core.outbox rows to mask / masked
    contents: int = 0           # ledger.content rows to redact / redacted
    events: int = 0             # redaction entries to append / appended
    scan_rows: int = 0          # project ledger.outbox rows with a secret shape (scan only)
    rotate: list = field(default_factory=list)   # (item_id, path, count)
    error: str | None = None


def _db():
    from platform_service import db

    return db


def _after_redaction_append() -> None:
    """Test hook: a crash between the append of a redaction entry and the update of its contents."""


# What is there


def _leaked_rows(log: str) -> list[dict]:
    """event_id, item_id and content of the accepted configuration contents of `log` still holding a plaintext
    secret, by event id."""
    with _db().pool().connection() as conn:
        rows = conn.execute(
            "SELECT c.event_id, i.item_id, c.content FROM ledger.content c"
            " JOIN ledger.event_index i ON (i.log, i.event_id) = (c.log, c.event_id)"
            " WHERE c.log = %s AND i.action = %s AND i.reason IS NULL AND c.content IS NOT NULL"
            " AND c.redacted_at IS NULL", (log, CONFIGURED)).fetchall()
    kept = [r for r in rows if isinstance(r["content"], dict) and holds_plaintext_secret(r["content"].get("config"))]
    return sorted(kept, key=lambda r: r["event_id"])


def leaked_contents(log: str) -> list[str]:
    """The event ids of the frozen configuration contents of `log` still holding a plaintext secret, ascending."""
    return [r["event_id"] for r in _leaked_rows(log)]


def redaction_event_id(log: str, reason: str, event_ids: list[str]) -> str:
    return str(uuid.uuid5(NAMESPACE, log + "\n" + reason + "\n" + "\n".join(event_ids)))


def _outbox_rows(pid: str) -> list[dict]:
    """The engine's configuration rows of `pid` whose masked content differs: event_id, item_id, content, masked."""
    with _db().pool().connection() as conn:
        rows = conn.execute(
            "SELECT event_id::text AS event_id, item_id, content FROM core.outbox"
            " WHERE emitter = 'engine' AND action = %s AND project_pid = %s ORDER BY occurred_at, event_id",
            (CONFIGURED, pid)).fetchall()
    changed = []
    for row in rows:
        content = row["content"]
        if not isinstance(content, dict) or "config" not in content:
            continue
        masked = {**content, "config": masked_for_ledger(content["config"])}
        if masked != content:
            changed.append({**row, "masked": masked})
    return changed


def _shaped(value) -> bool:
    if isinstance(value, str):
        return bool(SECRET_SHAPE.search(value))
    if isinstance(value, dict):
        return any(_shaped(inner) for inner in value.values())
    if isinstance(value, list):
        return any(_shaped(item) for item in value)
    return False


def _scan(pid: str) -> int:
    """The project database's own ledger.outbox rows holding a secret-shaped string (never changed)."""
    from platform_service.ledger import relay

    project = relay._project_conn(pid)
    if project is None:
        return 0
    try:
        rows = project.execute("SELECT content, before, after, details FROM ledger.outbox").fetchall()
    finally:
        project.close()
    return sum(1 for row in rows if any(_shaped(row[k]) for k in ("content", "before", "after", "details")))


def _rotate(outbox: list[dict], leaked: list[dict]) -> list[tuple[str, str, int]]:
    named: dict[tuple[str, str], set[str]] = {}
    for row in [*outbox, *leaked]:
        for path in plaintext_secret_paths(row["content"].get("config")):
            named.setdefault((str(row["item_id"]), path), set()).add(str(row["event_id"]))
    return sorted((item_id, path, len(ids)) for (item_id, path), ids in named.items())


def _chunks(ids: list[str]) -> list[list[str]]:
    return [ids[i:i + CHUNK] for i in range(0, len(ids), CHUNK)]


def _projects(pids: list[str] | None) -> list[str]:
    if pids:
        return sorted(set(pids))
    with _db().pool().connection() as conn:
        found = {r["pid"] for r in conn.execute(
            "SELECT DISTINCT project_pid::text AS pid FROM core.outbox"
            " WHERE emitter = 'engine' AND action = %s AND project_pid IS NOT NULL", (CONFIGURED,)).fetchall()}
        logs = conn.execute(
            "SELECT DISTINCT c.log, c.project_pid::text AS pid FROM ledger.content c"
            " JOIN ledger.event_index i ON (i.log, i.event_id) = (c.log, c.event_id)"
            " WHERE i.action = %s AND i.reason IS NULL AND c.content IS NOT NULL AND c.redacted_at IS NULL"
            " AND c.project_pid IS NOT NULL", (CONFIGURED,)).fetchall()
    found.update(r["pid"] for r in logs if leaked_contents(r["log"]))
    return sorted(found)


# Count and apply


def count(pids: list[str] | None = None) -> list[ProjectCounts]:
    """What `apply` would change, per project; nothing is written."""
    from platform_service.ledger import provision

    out = []
    for pid in _projects(pids):
        log = provision.database_for(pid)
        outbox = _outbox_rows(pid)
        leaked = _leaked_rows(log) if log else []
        out.append(ProjectCounts(pid, outbox_rows=len(outbox), contents=len(leaked),
                                 events=len(_chunks([r["event_id"] for r in leaked])), scan_rows=_scan(pid),
                                 rotate=_rotate(outbox, leaked)))
    return out


def apply(pids: list[str] | None = None, reason: str = REASON) -> list[ProjectCounts]:
    """Mask the outbox rows, redact the leaked contents and log each redaction, per project."""
    from platform_service.ledger import provision, relay
    from platform_service.ledger.store import LedgerError, LedgerUnavailable, TamperAlarm

    out = []
    for pid in _projects(pids):
        counts = ProjectCounts(pid, scan_rows=_scan(pid))
        log = provision.database_for(pid)
        if log is None:
            outbox = _mask_outbox(pid)
            counts.outbox_rows, counts.rotate = len(outbox), _rotate(outbox, [])
            out.append(counts)
            continue
        try:
            with relay._log_lock(log, wait=30.0):
                outbox = _mask_outbox(pid)
                counts.outbox_rows, counts.rotate = len(outbox), _rotate(outbox, [])
                leaked = _leaked_rows(log)
                counts.rotate = _rotate(outbox, leaked)
                for chunk in _chunks([r["event_id"] for r in leaked]):
                    counts.contents += _redact(log, pid, reason, chunk)
                    counts.events += 1
        except TamperAlarm:                       # the log does not verify: stop, write nothing more anywhere
            counts.error = LEDGER_ALARM
            out.append(counts)
            break
        except LedgerUnavailable:
            counts.error = LEDGER_DOWN
        except LedgerError as exc:
            counts.error = f"the ledger refused the redaction ({type(exc).__name__}); nothing redacted in this project"
        out.append(counts)
    return out


def _mask_outbox(pid: str) -> list[dict]:
    rows = _outbox_rows(pid)
    if rows:
        with _db().pool().connection() as conn:
            with conn.transaction():
                for row in rows:
                    conn.execute("UPDATE core.outbox SET content = %s WHERE event_id = %s",
                                 (Jsonb(row["masked"]), row["event_id"]))
    return rows


def _redact(log: str, pid: str, reason: str, chunk: list[str]) -> int:
    """Append (or find) the redaction entry naming `chunk`, index it, then redact the contents; how many."""
    from platform_service.ledger import registry, relay
    from platform_service.ledger.store import DuplicateEvent

    store = relay._store()
    entry = {"event_id": redaction_event_id(log, reason, chunk), "occurred_at": relay._iso(datetime.now(timezone.utc)),
             "project_pid": pid, "step": 0, "source_app": "platform", "action": ACTION, "actor_kind": "system",
             "actor_ref": None, "program": PROGRAM, "request_id": None, "item_type": "ledger", "item_id": log,
             "outcome": "ok", "details": {"event_ids": chunk, "reason": reason, "count": len(chunk)},
             "registry_version": registry.VERSION}
    try:
        seq = store.append(log, entry)
    except DuplicateEvent:                                            # an earlier run appended it, then stopped
        seq = store.seq_of(log, entry["event_id"])
        entry = store.get(log, seq).as_dict()
        if (entry.get("details") or {}).get("event_ids") != chunk:
            raise SecretCleanupError(f"redaction entry {entry['event_id']} is in the log with other event ids") \
                from None
    relay._index(log, seq, entry, pid)
    _after_redaction_append()
    with _db().pool().connection() as conn:
        with conn.transaction():
            cur = conn.execute("UPDATE ledger.content SET content = NULL, redacted_at = clock_timestamp(),"
                               " redaction = %s WHERE log = %s AND event_id = ANY(%s) AND redacted_at IS NULL",
                               (reason, log, chunk))
            return cur.rowcount


# The command line


def _print(results: list[ProjectCounts], applied: bool) -> int:
    words = (("rows_masked", "rows_redacted", "events_appended") if applied
             else ("rows_to_mask", "rows_to_redact", "events_to_append"))
    totals = [0, 0, 0, 0]
    failed = alarm = False
    for c in results:
        print(f"project {c.pid}: core.outbox {words[0]}={c.outbox_rows}")
        print(f"project {c.pid}: ledger.content {words[1]}={c.contents} {words[2]}={c.events}")
        print(f"project {c.pid}: ledger.outbox rows_with_secret_shape={c.scan_rows} (scan only)")
        for item_id, path, n in c.rotate:
            print(f"project {c.pid}: rotate item={item_id} field={path} events={n}")
        if c.error:
            print(f"project {c.pid}: {c.error}", file=sys.stderr)
            failed = True
            alarm = alarm or c.error == LEDGER_ALARM
        for i, n in enumerate((c.outbox_rows, c.contents, c.events, c.scan_rows)):
            totals[i] += n
    print(f"total: {words[0]}={totals[0]} {words[1]}={totals[1]} {words[2]}={totals[2]}"
          f" rows_with_secret_shape={totals[3]}")
    return ALARM_EXIT if alarm else 5 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m platform_service.ledger.secret_cleanup",
                                     description="Count or clean old plaintext plugin secrets in the platform's "
                                                 "copies of the engine's configuration events.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("count", "apply"):
        sub = commands.add_parser(name)
        sub.add_argument("--project", action="append", default=[], metavar="PID")
        if name == "apply":
            sub.add_argument("--reason", default=REASON)
    commands.add_parser("export").add_argument("pid")
    args = parser.parse_args(argv)
    if args.command == "export":
        from platform_service.ledger import export

        for line in export.lines(args.pid):
            print(json.dumps(line, default=str))
        return 0
    if args.command == "count":
        return _print(count(args.project or None), applied=False)
    return _print(apply(args.project or None, args.reason), applied=True)


if __name__ == "__main__":
    sys.exit(main())
