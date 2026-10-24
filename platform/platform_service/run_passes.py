"""A plugin run's pass to the internal connection routes.

The worker holds PLATFORM_CONNECTIONS_TOKEN, which opens every project's connections. A plugin is
catalogue code, so it never gets that token: before it starts, the worker asks for a pass naming the
run's own references (``target:<pid>/<key>``, ``connection:<pid>/<name>``), and the plugin presents the
pass instead. A pass opens the routes of exactly those references, until it expires or the worker revokes
it when the run ends. Only its hash is kept.

A pass may name the evaluation plugin it runs; then every connection resolved or run key issued under it is
recorded (record, uses_of), so results can say which connection a run reached and what it was then.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime

from platform_service import db

PREFIX = "aisc-rp-"
HEADER = "X-AISC-Run-Pass"


class Refused(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def _hash(run_pass: str) -> str:
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


def mint(refs, ttl_s: int | None = None, evaluation_plugin=None) -> tuple[str, datetime]:
    """A new pass for these references, and when it expires. `evaluation_plugin`, the uuid of the
    evaluation plugin the run is, is optional: a pass without one records no use."""
    if not isinstance(refs, list) or not refs:
        raise Refused(422, "refs: name the run's target or connection references")
    if evaluation_plugin is not None:
        try:
            evaluation_plugin = str(uuid.UUID(evaluation_plugin))
        except (ValueError, TypeError, AttributeError):
            raise Refused(422, "evaluation_plugin: the uuid of the evaluation plugin the run is") from None
    grants = sorted({_grant(ref) for ref in refs})
    for pid in {pid for _, pid, _ in grants}:
        if db.get_project(pid) is None:
            raise Refused(404, f"no project {pid!r}")
    ttl = ttl_s if ttl_s is not None else int(os.environ.get("CONNECTIONS_RUN_KEY_TTL_S") or 12 * 3600)
    run_pass = PREFIX + secrets.token_hex(32)
    with db.pool().connection() as conn:
        conn.execute("DELETE FROM core.run_pass WHERE expires_at < clock_timestamp()")
        expires = conn.execute(
            "INSERT INTO core.run_pass (pass_hash, refs, evaluation_plugin, expires_at)"
            " VALUES (%s, %s::jsonb, %s, clock_timestamp() + make_interval(secs => %s)) RETURNING expires_at",
            (_hash(run_pass), json.dumps([list(g) for g in grants]), evaluation_plugin, ttl)).fetchone()["expires_at"]
    return run_pass, expires


def check(run_pass: str, pid: str, kind: str, name: str) -> None:
    """Refused(401) for an unknown or expired pass, Refused(403) when it does not name this reference."""
    with db.pool().connection() as conn:
        row = conn.execute("SELECT refs FROM core.run_pass WHERE pass_hash = %s AND expires_at > clock_timestamp()",
                           (_hash(run_pass or ""),)).fetchone()
    if row is None:
        raise Refused(401, "unknown or expired run pass")
    try:
        project = str(uuid.UUID(pid))
    except ValueError:
        raise Refused(403, "this run pass does not open that") from None
    if [kind, project, name] not in row["refs"]:
        raise Refused(403, "this run pass does not open that")


def revoke(run_pass: str) -> None:
    with db.pool().connection() as conn:
        conn.execute("DELETE FROM core.run_pass WHERE pass_hash = %s", (_hash(run_pass or ""),))


def record(run_pass: str, pid: str, connection: str, protocol: str, fingerprint: str) -> None:
    """That this pass's run reached `connection` of project `pid`, of kind `protocol` and this fingerprint,
    now. Nothing for a pass that names no evaluation plugin, or one no longer open."""
    with db.pool().connection() as conn:
        conn.execute(
            "INSERT INTO core.run_pass_use (pass_hash, evaluation_plugin, pid, connection, protocol, fingerprint)"
            " SELECT pass_hash, evaluation_plugin, %s, %s, %s, %s FROM core.run_pass"
            " WHERE pass_hash = %s AND evaluation_plugin IS NOT NULL AND expires_at > clock_timestamp()",
            (pid, connection, protocol, fingerprint, _hash(run_pass or "")))


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
