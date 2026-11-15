"""A plugin run's pass to the internal connection routes.

The worker holds PLATFORM_CONNECTIONS_TOKEN, which opens every project's connections. A plugin is
catalogue code, so it never gets that token: before it starts, the worker asks for a pass naming the
run's own references (``target:<pid>/<key>``, ``connection:<pid>/<name>``), and the plugin presents the
pass instead. A pass opens the routes of exactly those references, until it expires or the worker revokes
it when the run ends. Only its hash is kept.

A pass may name the evaluation plugin it runs; then every connection resolved or run key issued under it is
recorded (record, uses_of), so results can say which connection a run reached and what it was then.

A call a door opened under a pass is in flight until its row is in the run's trace (call_started, call_ended).
Ending the pass refuses new calls at once, but its trace is sealed only when its calls in flight have been
recorded: revoke waits for them up to DRAIN_WAIT_S, and past that the last of them seals it. So a call answered
after a Stop, or after the plugin was killed mid-call, is in the seal and in the run's calls file. The count is
this process's: the platform serves the doors and these routes from one process.
"""
from __future__ import annotations

import hashlib
import json
import os
import logging
import secrets
import threading
import uuid
from datetime import datetime

from platform_service import db

PREFIX = "aisc-rp-"
HEADER = "X-AISC-Run-Pass"
#: seconds the end of a pass, or the read of its trace, waits for the calls still in flight under it; below the
#: worker's own wait for those routes (30 s), so the worker hears back either way
DRAIN_WAIT_S = 20

logger = logging.getLogger(__name__)


class Refused(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def hash_of(run_pass: str) -> str:
    """What is stored of a pass (sha256 hex): core.run_pass's key, and a run key's pass_hash."""
    return hashlib.sha256(run_pass.encode()).hexdigest()


def _grant(ref) -> tuple[str, str, str]:
    """("target" or "connection", project pid, key or name) of a reference; Refused(422) otherwise."""
    # where the routes import the plugin interface too: only a call that reads a reference needs it
    from aisc_plugin_interface.connections import BadReference, parse_reference
    from aisc_plugin_interface.targets import parse_target

    try:
        if isinstance(ref, str) and ref.startswith("target:"):
            pid, key = parse_target(ref)
            kind = "target"
        else:
            pid, key = parse_reference(ref)
            kind = "connection"
        return kind, str(uuid.UUID(pid)), key
    except (BadReference, ValueError, TypeError):
        raise Refused(422, f"not a target or connection reference: {ref!r}") from None


def mint(refs, ttl_s: int | None = None, evaluation_plugin=None, *, project) -> tuple[str, datetime]:
    """A new pass for these references, and when it expires. `project` is the platform pid of the
    evaluation's project: every reference must be of that project (403 otherwise), so a run never opens
    another project's targets or connections. `evaluation_plugin`, the uuid of the evaluation plugin the
    run is, is optional: a pass without one records no use."""
    if not isinstance(refs, list) or not refs:
        raise Refused(422, "refs: name the run's target or connection references")
    try:
        project_pid = str(uuid.UUID(project))
    except (ValueError, TypeError, AttributeError):
        raise Refused(422, "project: the platform pid of the evaluation's project") from None
    if evaluation_plugin is not None:
        try:
            evaluation_plugin = str(uuid.UUID(evaluation_plugin))
        except (ValueError, TypeError, AttributeError):
            raise Refused(422, "evaluation_plugin: the uuid of the evaluation plugin the run is") from None
    parsed = [(ref, _grant(ref)) for ref in refs]
    for ref, (_, pid, _) in parsed:
        if pid != project_pid:
            raise Refused(403, f"{ref!r} is not of the run's project {project_pid}")
    grants = sorted({grant for _, grant in parsed})
    if db.get_project(project_pid) is None:
        raise Refused(404, f"no project {project_pid!r}")
    ttl = ttl_s if ttl_s is not None else int(os.environ.get("CONNECTIONS_RUN_KEY_TTL_S") or 12 * 3600)
    run_pass = PREFIX + secrets.token_hex(32)
    with db.pool().connection() as conn:
        conn.execute("DELETE FROM core.run_pass WHERE expires_at < clock_timestamp()")
        expires = conn.execute(
            "INSERT INTO core.run_pass (pass_hash, refs, evaluation_plugin, expires_at)"
            " VALUES (%s, %s::jsonb, %s, clock_timestamp() + make_interval(secs => %s)) RETURNING expires_at",
            (hash_of(run_pass), json.dumps([list(g) for g in grants]), evaluation_plugin, ttl)).fetchone()["expires_at"]
    return run_pass, expires


def check(run_pass: str, pid: str, kind: str, name: str) -> None:
    """Refused(401) for an unknown or expired pass, Refused(403) when it does not name this reference."""
    with db.pool().connection() as conn:
        row = conn.execute("SELECT refs FROM core.run_pass WHERE pass_hash = %s AND expires_at > clock_timestamp()",
                           (hash_of(run_pass or ""),)).fetchone()
    if row is None:
        raise Refused(401, "unknown or expired run pass")
    try:
        project = str(uuid.UUID(pid))
    except ValueError:
        raise Refused(403, "this run pass does not open that") from None
    if [kind, project, name] not in row["refs"]:
        raise Refused(403, "this run pass does not open that")


def expires_at(run_pass: str) -> datetime | None:
    """When a live pass expires; None for an unknown or expired one."""
    with db.pool().connection() as conn:
        row = conn.execute("SELECT expires_at FROM core.run_pass WHERE pass_hash = %s"
                           " AND expires_at > clock_timestamp()", (hash_of(run_pass or ""),)).fetchone()
    return row["expires_at"] if row else None


def live_evaluation_plugin(pass_hash: str) -> tuple[bool, str | None]:
    """(whether the pass of this hash is still open, the evaluation plugin it names) in one read."""
    with db.pool().connection() as conn:
        row = conn.execute("SELECT evaluation_plugin::text AS e FROM core.run_pass WHERE pass_hash = %s"
                           " AND expires_at > clock_timestamp()", (pass_hash,)).fetchone()
    return (row is not None, row["e"] if row else None)


def is_live(pass_hash: str) -> bool:
    """Whether the pass of this hash is still open (a run key under it may be used)."""
    with db.pool().connection() as conn:
        return conn.execute("SELECT 1 FROM core.run_pass WHERE pass_hash = %s AND expires_at > clock_timestamp()",
                            (pass_hash,)).fetchone() is not None


def projects_of(pass_hash: str) -> list[str]:
    """The projects a live pass's references name (sorted, unique); [] for none."""
    with db.pool().connection() as conn:
        row = conn.execute("SELECT refs FROM core.run_pass WHERE pass_hash = %s AND expires_at > clock_timestamp()",
                           (pass_hash,)).fetchone()
    return sorted({ref[1] for ref in row["refs"]}) if row else []


class _Flight:
    """The calls in flight under one pass, and the seal its end left for the last of them to make."""
    def __init__(self, pass_hash: str):
        self.pass_hash, self.calls, self.seal = pass_hash, 0, None


_flights: dict[str, _Flight] = {}
_flight_lock = threading.Condition()


def call_started(run_id: str) -> _Flight | None:
    """Count a call a door is opening under the pass of `run_id` ("pass:<hash>"), until call_ended. None for a
    run key issued without a pass, which has no seal to wait for. The caller then checks the pass is still live
    (is_live): a pass that ended before the call was counted gets no call."""
    kind, _, pass_hash = run_id.partition(":")
    if kind != "pass":
        return None
    with _flight_lock:
        flight = _flights.setdefault(pass_hash, _Flight(pass_hash))
        flight.calls += 1
        return flight


def call_ended(flight: _Flight | None) -> None:
    """The call is recorded (or was never made). The last call of a pass whose end did not wait for it seals the
    run's trace now."""
    if flight is None:
        return
    with _flight_lock:
        flight.calls -= 1
        seal = None
        if flight.calls == 0:
            seal, flight.seal = flight.seal, None
            if _flights.get(flight.pass_hash) is flight:
                del _flights[flight.pass_hash]
        _flight_lock.notify_all()
    if seal is not None:
        try:
            _seal(**seal)
        except Exception:
            logger.exception("the trace of an ended run pass was not sealed after its last call")


def _drained(pass_hash: str, wait_s: float, seal: dict | None = None) -> bool:
    """Whether no call is in flight under the pass, waiting up to wait_s for those that are. When they are still
    in flight, `seal` is left for the last of them to make (call_ended)."""
    with _flight_lock:
        done = _flight_lock.wait_for(lambda: pass_hash not in _flights, timeout=wait_s)
        if not done and seal is not None:
            _flights[pass_hash].seal = seal
        return done


def wait_for_calls(pass_hash: str, wait_s: float = DRAIN_WAIT_S) -> bool:
    """Wait up to wait_s for the calls in flight under the pass to be recorded; whether they all were."""
    return _drained(pass_hash, wait_s)


def _seal(pass_hash: str, evaluation_plugin: str, projects: list[str], request_id: str | None,
          run_id: str | None) -> None:
    """A run.trace.sealed event {calls, digest} (run_trace.seal) of the run's trace in each project."""
    from platform_service import run_trace
    from platform_service.ledger import outbox

    with db.pool().connection() as conn, conn.transaction():
        for pid in projects:
            outbox.emit(conn, "run.trace.sealed", project_pid=pid, item_type="evaluation_plugin",
                        item_id=evaluation_plugin, details=run_trace.seal(pid, f"pass:{pass_hash}"),
                        request_id=request_id, run_id=run_id)


def revoke(run_pass: str, *, request_id: str | None = None, run_id: str | None = None) -> list[str]:
    """End a pass; the projects its references named (sorted, unique), whose run keys under it the
    caller deletes. [] for an unknown pass.

    A pass that names its evaluation plugin also seals that run's call trace in each project, once the calls in
    flight under it are recorded (see the module's notes): a run.trace.sealed event {calls, digest}
    (run_trace.seal), citing the request and the run the worker names (the run its evaluation started), so the
    ledger holds the digest the trace's export must end with."""
    pass_hash = hash_of(run_pass or "")
    with db.pool().connection() as conn, conn.transaction():
        row = conn.execute("DELETE FROM core.run_pass WHERE pass_hash = %s RETURNING refs, evaluation_plugin::text",
                           (pass_hash,)).fetchone()
    projects = sorted({ref[1] for ref in row["refs"]}) if row else []
    if row and row["evaluation_plugin"]:
        seal = {"pass_hash": pass_hash, "evaluation_plugin": row["evaluation_plugin"], "projects": projects,
                "request_id": request_id, "run_id": run_id}
        if _drained(pass_hash, DRAIN_WAIT_S, seal):
            _seal(**seal)
    return projects


def record(run_pass: str, pid: str, connection: str, protocol: str, fingerprint: str) -> None:
    """That this pass's run reached `connection` of project `pid`, of kind `protocol` and this fingerprint,
    now. Nothing for a pass that names no evaluation plugin, or one no longer open."""
    with db.pool().connection() as conn:
        conn.execute(
            "INSERT INTO core.run_pass_use (pass_hash, evaluation_plugin, pid, connection, protocol, fingerprint)"
            " SELECT pass_hash, evaluation_plugin, %s, %s, %s, %s FROM core.run_pass"
            " WHERE pass_hash = %s AND evaluation_plugin IS NOT NULL AND expires_at > clock_timestamp()",
            (pid, connection, protocol, fingerprint, hash_of(run_pass or "")))


def uses_of(evaluation_plugin, pid=None) -> list[dict]:
    """The connections an evaluation plugin's runs reached, in the order first reached: pid, connection,
    protocol (its kind then), fingerprint (then), used_at (the first time). A connection reached again as
    it was (a retry, its resolve then its run key) is one use; changed in between, it is two. Only
    project `pid`'s when given."""
    with db.pool().connection() as conn:
        return conn.execute(
            "SELECT pid::text AS pid, connection, protocol, fingerprint, min(used_at) AS used_at"
            " FROM core.run_pass_use WHERE evaluation_plugin = %s AND (%s::uuid IS NULL OR pid = %s::uuid)"
            " GROUP BY pid, connection, protocol, fingerprint ORDER BY min(used_at), min(id)",
            (str(evaluation_plugin), pid, pid)).fetchall()


def uses_by_run(evaluation_plugins, pid) -> dict[str, list[dict]]:
    """uses_of for several evaluation plugins of project `pid` at once: {evaluation plugin: its uses}, only
    those with some."""
    if not evaluation_plugins:
        return {}
    with db.pool().connection() as conn:
        rows = conn.execute(
            "SELECT evaluation_plugin::text AS evaluation_plugin, connection, protocol, fingerprint,"
            " min(used_at) AS used_at FROM core.run_pass_use"
            " WHERE evaluation_plugin = ANY(%s::uuid[]) AND pid = %s::uuid"
            " GROUP BY evaluation_plugin, connection, protocol, fingerprint ORDER BY min(used_at), min(id)",
            ([str(e) for e in evaluation_plugins], str(pid))).fetchall()
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r.pop("evaluation_plugin"), []).append(r)
    return out
