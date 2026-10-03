"""The relay (spec 4.2-4.5, 7.2; I2, I3, I6, I9, I11): moves witness records and events into their logs.

For each log (a project's database, or the platform's own), under that log's advisory lock:
- witness records (`ledger.witness`) become `request.witnessed` / `request.unverified` entries;
- events from the platform's `core.outbox` and the project database's `ledger.outbox` become trusted
  entries if they fit the request they cite, and `ledger.rejected` entries if they don't.

Each item is processed in three idempotent steps: append to the store (idempotent on event id and
content), add the index row (ON CONFLICT DO NOTHING), mark it delivered. A crash anywhere re-runs to the
same result. Nothing is read by a high-water mark, so a late commit is never skipped. A log whose store
is unreachable, or whose database the current store doesn't hold, stays pending; the other logs go on.
"""
from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

import logging

from platform_service.ledger import registry, secrets, settings
from platform_service.ledger.canonical import canonical
from platform_service.ledger.naming import PLATFORM_DB
from platform_service.ledger.store import DuplicateEvent, EntryTooLarge, LedgerError, LedgerUnavailable, UnknownDatabase

logger = logging.getLogger(__name__)

#: Which app a project database role is (spec 6.5).
ROLE_APP = {"qualification_rw": "qualification", "controls_rw": "controls",
            "control_objectives_rw": "control_objectives", "report_composer_rw": "report_composer",
            "platform_rw": "platform"}
_EVENT_COLUMNS = ("event_id", "occurred_at", "request_id", "run_id", "action", "item_type", "item_id",
                  "item_version", "card_version", "content", "before", "after", "details", "outcome",
                  "registry_version", "model", "extra")


@dataclass
class RelayStats:
    delivered: int = 0
    rejected: int = 0
    held: int = 0
    pending: int = 0


class _Hold(Exception):
    """Not yet: an action from a newer registry (R2.12)."""


def _db():
    from platform_service import db

    return db


def _store():
    from platform_service import ledger

    return ledger.current()


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


@contextmanager
def _log_lock(log: str, wait: bool = True):
    """The log's relay lock (spec 7.2): two relays never interleave on one log. On its own connection,
    never one of the platform pool's (review m1). The relay tries it (`wait=False`) and leaves a busy
    log for its next pass; an admin's re-anchor waits for it. Yields whether it is held."""
    key = "ledger-relay:" + log
    with psycopg.connect(_db().dsn(), autocommit=True) as conn:
        if wait:
            conn.execute("SELECT pg_advisory_lock(hashtext(%s))", (key,))
            held = True
        else:
            held = conn.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (key,)).fetchone()[0]
        try:
            yield held
        finally:
            if held:
                conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (key,))


def _after_index(item) -> None:
    """Test hook (review M7): a crash between the index and the mark."""


def _project_dsn(pid: str) -> str:
    from platform_service import projectdb

    return make_conninfo(_db().dsn(), dbname=projectdb.database_name(pid))


def _project_conn(pid: str):
    try:
        return psycopg.connect(_project_dsn(pid), row_factory=dict_row, autocommit=True)
    except psycopg.OperationalError:
        return None                                                   # the project database is gone


def relay_once(pid: str | None = None) -> RelayStats:
    """Relay one project's log, or (pid None) every project's and the platform's own."""
    stats = RelayStats()
    if pid is not None:
        _relay_log(str(pid), stats)
        return stats
    for each in [*_projects_with_work(), None]:                       # the platform log last
        try:
            _relay_log(each, stats)
        except LedgerError:                                           # never abort the batch (M4)
            stats.pending += 1
        except Exception:                                             # a bug in one log never stops the others
            logger.exception("ledger: relaying %s failed", each or "the platform log")
            stats.pending += 1
    return stats


def _projects_with_work() -> list[str]:
    with _db().pool().connection() as conn:
        rows = conn.execute(
            "SELECT pid::text AS pid FROM core.project"
            " UNION SELECT project_pid::text FROM ledger.witness WHERE project_pid IS NOT NULL AND delivered_seq IS NULL"
            " UNION SELECT project_pid::text FROM core.outbox WHERE project_pid IS NOT NULL AND delivered_at IS NULL"
        ).fetchall()
    return sorted(r["pid"] for r in rows)


def _relay_log(pid: str | None, stats: RelayStats) -> None:
    from platform_service.ledger import provision

    log = PLATFORM_DB if pid is None else provision.database_for(pid)
    items = None
    if log is None:                                                   # no database yet: everything waits
        stats.pending += len(_pending(pid, None))
        return
    with _log_lock(log, wait=False) as held:
        if not held:                                                  # another relay is on it: next pass
            stats.pending += 1
            return
        project = _project_conn(pid) if pid is not None else None
        try:
            items = _pending(pid, project)
            for n, item in enumerate(items):
                try:
                    _process(item, pid, log, project, stats)
                except _Hold:
                    stats.held += 1
                except (LedgerUnavailable, UnknownDatabase):
                    stats.pending += len(items) - n
                    return
        finally:
            if project is not None:
                project.close()


def _pending(pid, project) -> list[dict]:
    """The next batch not delivered yet for this log, oldest first (time, then kind, then id). Each source
    gives at most RELAY_BATCH rows in time order; a source cut short sets a cutoff, and only what is
    before every cutoff is relayed this pass, so the merged order is never wrong (review M1)."""
    limit = settings.RELAY_BATCH
    sources = []
    with _db().pool().connection() as conn:
        where = "project_pid IS NULL" if pid is None else "project_pid = %s"
        args = () if pid is None else (pid,)
        sources.append([{"kind": "witness", "at": row["at"], "row": dict(row)} for row in conn.execute(
            f"SELECT * FROM ledger.witness WHERE {where} AND delivered_seq IS NULL ORDER BY at, request_id LIMIT %s",
            (*args, limit))])
        sources.append([{"kind": "core", "at": row["occurred_at"], "row": dict(row)} for row in conn.execute(
            f"SELECT * FROM core.outbox WHERE {where} AND delivered_at IS NULL ORDER BY occurred_at, event_id LIMIT %s",
            (*args, limit))])
    if project is not None:
        sources.append([{"kind": "project", "at": row["occurred_at"], "row": dict(row)} for row in project.execute(
            "SELECT o.* FROM ledger.outbox o LEFT JOIN ledger.delivered d ON d.event_id = o.event_id"
            " WHERE d.event_id IS NULL ORDER BY o.occurred_at, o.event_id LIMIT %s", (limit,))])
    cutoffs = [rows[-1]["at"] for rows in sources if len(rows) >= limit]
    order = {"witness": 0, "core": 1, "project": 2}
    items = sorted((i for rows in sources for i in rows),
                   key=lambda i: (i["at"], order[i["kind"]], str(i["row"].get("event_id") or i["row"].get("request_id"))))
    if cutoffs:
        cutoff = min(cutoffs)
        items = [i for i in items if i["at"] <= cutoff]
    return items


def _process(item: dict, pid, log: str, project, stats: RelayStats) -> None:
    if item["kind"] == "witness":
        _deliver_witness(item["row"], pid, log, stats)
    else:
        _deliver_event(item, pid, log, project, stats)


# --- witness records ---------------------------------------------------------------------------------

def _indexed(log: str, event_id: str, digest: str) -> dict | None:
    """The index row of this very row, already relayed (accepted, or rejected): same event id, same
    content. A re-sent row whose content differs is not it, and goes on to the duplicate alarm."""
    with _db().pool().connection() as conn:
        return conn.execute("SELECT seq, reason FROM ledger.event_index WHERE log = %s AND row_digest = %s"
                            " AND (event_id = %s OR (action = 'ledger.rejected' AND item_id = %s))"
                            " ORDER BY seq DESC LIMIT 1", (log, digest, event_id, event_id)).fetchone()


def _deliver_witness(w: dict, pid, log: str, stats: RelayStats) -> None:
    entry = {
        "event_id": f"witness:{w['request_id']}", "occurred_at": _iso(w["at"]), "project_pid": pid,
        "step": 0, "source_app": w["app"], "action": "request.witnessed" if w["verified"] else "request.unverified",
        "actor_kind": "user", "actor_ref": w["actor_ref"], "request_id": str(w["request_id"]),
        "next_action": w["next_action"], "verified": w["verified"], "item_type": "request",
        "item_id": str(w["request_id"]), "outcome": "ok",
        "details": {"method": w["method"], "path": w["route_path"], "member": w["member"],
                    **({"reason": w["reason"]} if w["reason"] else {}),
                    **({"query": w["query_hmac"]} if w["query_hmac"] else {})},
        "registry_version": registry.VERSION,
    }
    try:
        seq = _store().append(log, entry)
    except DuplicateEvent:                                            # rebuilt after an upgrade: the stored
        seq = _store().seq_of(log, entry["event_id"])                 # entry is the record (review B1)
        entry = _store().get(log, seq).as_dict()
    _index(log, seq, entry, pid)
    with _db().pool().connection() as conn:
        conn.execute("UPDATE ledger.witness SET delivered_seq = %s WHERE request_id = %s", (seq, w["request_id"]))
    stats.delivered += 1


# --- events -----------------------------------------------------------------------------------------

def _event_of(item: dict, pid) -> tuple[dict, str | None]:
    """The event as the emitter sent it, and the emitting app."""
    row = item["row"]
    ev = {k: row.get(k) for k in _EVENT_COLUMNS}
    ev["event_id"] = str(row["event_id"])
    for k in ("request_id", "run_id", "card_version"):
        ev[k] = str(ev[k]) if ev[k] is not None else None
    if item["kind"] == "core":
        app = row["emitter"]
        ev["project_pid"] = str(row["project_pid"]) if row["project_pid"] else None
    else:
        app = ROLE_APP.get(row["db_role"])
        ev["project_pid"] = pid
    return ev, app


def _deliver_event(item: dict, pid, log: str, project, stats: RelayStats) -> None:
    ev, app = _event_of(item, pid)
    digest = hashlib.sha256(_row_digest(ev)).hexdigest()
    done = _indexed(log, ev["event_id"], digest)
    if done is not None:                                              # a crash after the index: only mark it
        _mark(item, project, done["seq"], done["reason"])
        stats.delivered += 1
        return
    held = _store().seq_of(log, ev["event_id"])
    if held is not None:                                              # the store has this id already
        if _index_has(log, ev["event_id"]):
            _reject(item, ev, app, pid, log, project, "duplicate_event_id", stats)   # other content (I3)
            return
        entry = _store().get(log, held).as_dict()                     # a crash after the append (review m5):
        _index(log, held, entry, pid, row_digest=digest)              # the stored entry is the record,
        _freeze(log, entry["event_id"], pid, ev)                      # never judged again
        _after_index(item)
        _mark(item, project, held, None)
        stats.delivered += 1
        return
    try:
        entry = _judge(ev, app, pid, log, project)
    except _Rejected as rejection:
        _reject(item, ev, app, pid, log, project, rejection.reason, stats)
        return
    except (ValueError, TypeError):                                   # canonical JSON refuses a value (B1)
        _reject(item, ev, app, pid, log, project, "unencodable", stats)
        return
    bind = entry.pop("_bind", None)
    try:
        seq = _store().append(log, entry)
    except DuplicateEvent:
        _reject(item, ev, app, pid, log, project, "duplicate_event_id", stats)
        return
    except EntryTooLarge:                                             # never a stall of the log (review M5)
        _reject(item, ev, app, pid, log, project, "too_large", stats)
        return
    except (ValueError, TypeError):
        _reject(item, ev, app, pid, log, project, "unencodable", stats)
        return
    if bind is not None:                                              # learnt from accepted events only (M2)
        _learn_action(*bind)
    _index(log, seq, entry, pid, row_digest=digest)
    _freeze(log, entry["event_id"], pid, ev)
    _after_index(item)
    _mark(item, project, seq, None)
    stats.delivered += 1


def _index_has(log: str, event_id: str) -> bool:
    with _db().pool().connection() as conn:
        return conn.execute("SELECT 1 FROM ledger.event_index WHERE log = %s AND event_id = %s",
                            (log, event_id)).fetchone() is not None


class _Rejected(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _judge(ev: dict, app: str | None, pid, log: str, project) -> dict:
    """The trusted entry for an event, or _Rejected with the first failing check (spec 4.2), or _Hold."""
    action = registry.REGISTRY.get(ev["action"])
    if action is None:
        version = ev.get("registry_version") or 0
        age = datetime.now(timezone.utc) - ev["occurred_at"] if ev.get("occurred_at") else None
        # one version ahead (the next deploy), for HOLD_UNKNOWN at most (R2.12; review M4)
        if version == registry.VERSION + 1 and (age is None or age < settings.HOLD_UNKNOWN):
            raise _Hold()
        raise _Rejected("unknown_action")
    if app is None:
        raise _Rejected("emitter")
    sent = {k: v for k, v in ev.items() if k not in ("extra", "occurred_at", "project_pid", "registry_version")
            and v is not None}
    sent.update(ev.get("extra") or {})
    problems = registry.check(sent, emitter=app)
    if problems:
        raise _Rejected(problems[0])

    base = {
        "event_id": ev["event_id"], "occurred_at": _iso(ev["occurred_at"]), "project_pid": ev["project_pid"],
        "step": action.step, "source_app": app, "action": ev["action"], "item_type": ev["item_type"],
        "item_id": ev["item_id"], "item_version": ev["item_version"], "card_version": ev["card_version"],
        "request_id": ev["request_id"], "run_id": ev["run_id"], "outcome": ev["outcome"] or "ok",
        "details": ev["details"] or {}, "registry_version": registry.VERSION,
        "content_sha256": secrets.content_digest(pid, ev["content"]) if ev["content"] is not None else None,
        "before_sha256": secrets.state_digest(pid, ev["before"]) if ev["before"] is not None else None,
        "after_sha256": secrets.state_digest(pid, ev["after"]) if ev["after"] is not None else None,
    }
    if {"ai", "worker"} & set(action.actor_kinds) and "user" not in action.actor_kinds:
        return {**base, **_judge_run(ev, app, action, log)}
    return {**base, **_judge_request(ev, app, action, pid, log, project)}


def _judge_request(ev, app, action, pid, log, project) -> dict:
    if not ev["request_id"]:
        raise _Rejected("missing_request")
    w = _witness(ev["request_id"])
    if w is None:
        raise _Rejected("unknown_request")
    if (str(w["project_pid"]) if w["project_pid"] else None) != ev["project_pid"]:
        raise _Rejected("project_mismatch")
    matched = _cause(action, w)
    if matched is None:
        raise _Rejected("cause")
    entry_app, method, pattern = matched
    m = re.match(pattern, w["route_path"])
    if m and "item" in m.groupdict() and m.group("item") != ev["item_id"]:
        raise _Rejected("item")
    delta = ev["occurred_at"] - w["at"]
    if delta > settings.WINDOW:
        raise _Rejected("stale_request")
    if delta < -settings.CLOCK_SKEW:
        raise _Rejected("early_event")
    if action.per_request is not None and _accepted_count(log, ev["request_id"], ev["action"]) >= action.per_request:
        raise _Rejected("per_request")
    bind = None
    if method == "ACTION" and app == w["app"]:                        # the action id last (review M2)
        _check_action(w, ev["action"], project)
        bind = (w, ev["action"], project)
    return {"actor_kind": "user", "actor_ref": w["actor_ref"], "verified": bool(w["verified"]),
            "next_action": w["next_action"], "_bind": bind}


def _judge_run(ev, app, action, log) -> dict:
    """An AI or worker event (spec 4.4): its run's start event, accepted, citing the same request."""
    if not ev["request_id"] or not ev["run_id"]:
        raise _Rejected("run")
    w = _witness(ev["request_id"])
    if w is not None and (str(w["project_pid"]) if w["project_pid"] else None) != ev["project_pid"]:
        raise _Rejected("project_mismatch")                           # a run cites its own project's request
    with _db().pool().connection() as conn:
        rows = conn.execute(
            "SELECT seq, action, actor_ref, occurred_at FROM ledger.event_index WHERE log = %s AND run_id = %s"
            " AND request_id = %s AND reason IS NULL AND action NOT LIKE 'request.%%' ORDER BY seq",
            (log, ev["run_id"], ev["request_id"])).fetchall()
    # the start is the first accepted event of the run whose action starts runs (review m4)
    start = next((r for r in rows if r["action"] in registry.REGISTRY and registry.REGISTRY[r["action"]].runs), None)
    if start is None:
        raise _Rejected("run")
    logged = _store().get(log, start["seq"]).as_dict()               # the person comes from the log (review m12)
    if (logged.get("action"), logged.get("actor_ref"), logged.get("run_id"), logged.get("request_id")) != \
            (start["action"], start["actor_ref"], ev["run_id"], ev["request_id"]):
        logger.error("ledger %s: the index row of run %s disagrees with the log", log, ev["run_id"])
        raise _Rejected("index_mismatch")
    starter = registry.REGISTRY.get(start["action"])
    if starter is None or ev["action"] not in starter.runs:
        raise _Rejected("run")
    if ev.get("item_type") == logged.get("item_type") and ev.get("item_id") != logged.get("item_id"):
        raise _Rejected("run")                                        # the run's own item, never another (m4)
    if ev["occurred_at"] - start["occurred_at"] > starter.run_window:
        raise _Rejected("run_window")
    if ev["occurred_at"] < start["occurred_at"] - settings.CLOCK_SKEW:   # no run event before its start (m4)
        raise _Rejected("run")
    kind = "ai" if "ai" in action.actor_kinds else "worker"
    return {"actor_kind": kind, "actor_ref": None, "on_behalf_of_ref": start["actor_ref"], "program": app,
            "model": ev.get("model"), "verified": bool(logged.get("verified"))}   # the start's (review M3)


def _witness(request_id: str) -> dict | None:
    with _db().pool().connection() as conn:
        return conn.execute("SELECT * FROM ledger.witness WHERE request_id = %s", (request_id,)).fetchone()


def _cause(action, w) -> tuple | None:
    for entry in action.caused_by:
        app, method, pattern = entry
        if app != w["app"]:
            continue
        if method == "ACTION":
            if w["method"] != "POST":
                continue
        elif method != w["method"]:
            continue
        if re.match(pattern, w["route_path"]):
            return entry
    return None


def _check_action(w, action_name: str, project) -> None:
    """Spec 4.5: an action id is bound to the actions of the first request that has accepted events. This
    only checks; the binding learns after the event is accepted (`_learn_action`, review M2)."""
    if not w["next_action"]:
        raise _Rejected("action_id")
    if project is None:
        return
    row = project.execute("SELECT first_request, actions FROM ledger.action_binding WHERE app = %s AND next_action = %s",
                          (w["app"], w["next_action"])).fetchone()
    if row is None or str(row["first_request"]) == str(w["request_id"]):
        return
    action = registry.REGISTRY.get(action_name)
    same = {action_name, *(action.same_action if action else ())}
    if not same & set(row["actions"]):                                # another branch of the same action is fine
        raise _Rejected("action_id")


def _learn_action(w, action_name: str, project) -> None:
    if project is None:
        return
    project.execute("INSERT INTO ledger.action_binding (app, next_action, first_request, actions)"
                    " VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (w["app"], w["next_action"], w["request_id"], [action_name]))
    project.execute("UPDATE ledger.action_binding SET actions = array_append(actions, %s)"
                    " WHERE app = %s AND next_action = %s AND first_request = %s AND NOT (%s = ANY(actions))",
                    (action_name, w["app"], w["next_action"], w["request_id"], action_name))


def _accepted_count(log: str, request_id: str, action: str) -> int:
    with _db().pool().connection() as conn:
        return conn.execute("SELECT count(*) AS n FROM ledger.event_index WHERE log = %s AND request_id = %s"
                            " AND action = %s AND reason IS NULL", (log, request_id, action)).fetchone()["n"]


def _reject(item, ev, app, pid, log, project, reason: str, stats: RelayStats) -> None:
    digest = hashlib.sha256(_row_digest(ev)).hexdigest()
    entry = {
        "event_id": f"rejected:{ev['event_id']}:{digest[:16]}", "occurred_at": _iso(ev["occurred_at"]),
        "project_pid": ev.get("project_pid"), "step": 0, "source_app": app, "action": "ledger.rejected",
        "actor_kind": "system", "actor_ref": None, "program": "relay", "request_id": ev.get("request_id"),
        "item_type": "event", "item_id": ev["event_id"], "outcome": "refused",
        "details": {"reason": reason, "digest": digest}, "registry_version": registry.VERSION,
    }
    seq = _store().append(log, entry)
    _index(log, seq, entry, pid, reason=reason, row_digest=digest)
    _mark(item, project, seq, reason)
    stats.rejected += 1


def _row_digest(ev: dict) -> bytes:
    """What was sent, as canonical bytes (its digest names the rejected row in the log). A value canonical
    JSON refuses (an integer beyond 2**53) still gets a stable digest, so the row can be rejected."""
    clean = {k: (_iso(v) if isinstance(v, datetime) else v) for k, v in ev.items()}
    try:
        return canonical(json.loads(json.dumps(clean, default=str)))
    except (ValueError, TypeError):
        return b"unencodable:" + json.dumps(clean, default=str, sort_keys=True).encode()


def _mark(item, project, seq, reason) -> None:
    row = item["row"]
    if item["kind"] == "core":
        with _db().pool().connection() as conn:
            conn.execute("UPDATE core.outbox SET delivered_seq = %s, delivered_reason = %s,"
                         " delivered_at = clock_timestamp() WHERE event_id = %s", (seq, reason, row["event_id"]))
    elif project is not None:
        project.execute("INSERT INTO ledger.delivered (event_id, seq, reason) VALUES (%s, %s, %s)"
                        " ON CONFLICT (event_id) DO UPDATE SET seq = EXCLUDED.seq, reason = EXCLUDED.reason",
                        (row["event_id"], seq, reason))


def _index(log: str, seq: int, entry: dict, pid, reason: str | None = None, row_digest: str | None = None) -> None:
    with _db().pool().connection() as conn:
        conn.execute(
            "INSERT INTO ledger.event_index (log, seq, event_id, project_pid, action, actor_ref, step, source_app,"
            " item_type, item_id, card_version, outcome, occurred_at, request_id, run_id, before_sha256,"
            " after_sha256, reason, row_digest, actor_kind)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT DO NOTHING",
            (log, seq, entry["event_id"], pid, entry["action"], entry.get("actor_ref"), entry.get("step"),
             entry.get("source_app"), entry.get("item_type"), entry.get("item_id"), entry.get("card_version"),
             entry.get("outcome"), entry.get("occurred_at"), _uuid(entry.get("request_id")),
             _uuid(entry.get("run_id")), entry.get("before_sha256"), entry.get("after_sha256"), reason, row_digest,
             entry.get("actor_kind")))


def _uuid(value):
    if not value:
        return None
    try:
        import uuid

        return str(uuid.UUID(str(value)))
    except ValueError:
        return None


def _freeze(log: str, event_id: str, pid, ev: dict) -> None:
    """The content itself, outside the log (until the evidence store, phase 10)."""
    if ev["content"] is None and ev["before"] is None and ev["after"] is None:
        return
    with _db().pool().connection() as conn:
        conn.execute("INSERT INTO ledger.content (log, event_id, project_pid, content, before, after)"
                     " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                     (log, event_id, pid, _j(ev["content"]), _j(ev["before"]), _j(ev["after"])))


def _j(value):
    return None if value is None else json.dumps(value)
