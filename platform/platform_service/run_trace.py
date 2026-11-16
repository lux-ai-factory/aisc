"""The record of every call a run made to the system under test (project-template/0029_run_trace.sql).

The protocol doors (routes/facade.py) record each call they make, whatever plugin made the request, before
its answer goes back; a call that cannot be recorded gets no answer. Rows are append-only and chained per
run: a row's hash covers its own fields and the hash of the row before it, so the last hash (the digest)
changes when any row of the run is edited, inserted or removed. `export` gives a run's calls as JSON lines
ending with the seal {calls, digest}; `verify` recomputes the chain from those lines alone.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone

from platform_service import db, projectdb

OUTCOMES = ("answered", "failed", "not_sent")

#: the fields a call's hash covers, in the export's words
HASHED = ("seq", "connection", "door", "started_at", "ended_at", "request", "outcome", "answer", "error", "prev_hash")


def now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _canonical(fields: dict) -> bytes:
    return json.dumps({k: fields[k] for k in HASHED}, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode()


def hash_of(fields: dict) -> str:
    return hashlib.sha256(_canonical(fields)).hexdigest()


def storable(value):
    """`value` as the trace can keep it: jsonb takes no NUL character and no NaN or infinity, which JSON parsers
    accept. A NUL becomes the six characters \\u0000 and a non-finite number its name as a string ("NaN"), in
    keys and values alike; everything else stays as it is."""
    if isinstance(value, str):
        return value.replace("\x00", "\\u0000")
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
    if isinstance(value, dict):
        return {storable(k) if isinstance(k, str) else k: storable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [storable(v) for v in value]
    return value


def _evaluation_plugin(run: str) -> str | None:
    """The evaluation plugin the run's pass names, None for a key issued without a pass."""
    kind, _, digest = run.partition(":")
    if kind != "pass":
        return None
    with db.pool().connection() as conn:
        row = conn.execute("SELECT evaluation_plugin::text AS e FROM core.run_pass WHERE pass_hash = %s",
                           (digest,)).fetchone()
    return row["e"] if row else None


#: record's default: the evaluation plugin is read from the run's pass when the call is recorded
_FROM_THE_PASS = object()


def record(pid, run: str, connection: str, door: str, request: dict, outcome: str, answer: dict | None,
           error: dict | None, started_at: datetime, ended_at: datetime, evaluation_plugin=_FROM_THE_PASS) -> dict:
    """Append one call to its run's chain and give back the row as exported. Raises when it cannot (a value
    jsonb cannot keep, among others: see `storable`). The doors pass the evaluation plugin they read when the
    call opened: the pass may have ended by the time its answer comes back."""
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome: one of {', '.join(OUTCOMES)}")
    if evaluation_plugin is _FROM_THE_PASS:
        evaluation_plugin = _evaluation_plugin(run)
    with projectdb.connect(pid) as conn:
        with conn.transaction():
            # one writer per run at a time, so seq and prev_hash follow each other
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (run,))
            last = conn.execute("SELECT seq, hash FROM trace.call WHERE run = %s ORDER BY seq DESC LIMIT 1",
                                (run,)).fetchone()
            texts = [None if v is None else json.dumps(v, allow_nan=False) for v in (request, answer, error)]
            # hashed as jsonb keeps them (1e16 comes back as 10000000000000000), so an export verifies
            kept = conn.execute("SELECT %s::jsonb AS request, %s::jsonb AS answer, %s::jsonb AS error",
                                texts).fetchone()
            fields = {"seq": (last["seq"] + 1) if last else 1, "connection": connection, "door": door,
                      "started_at": _iso(started_at), "ended_at": _iso(ended_at), "request": kept["request"],
                      "outcome": outcome, "answer": kept["answer"], "error": kept["error"],
                      "prev_hash": last["hash"] if last else None}
            fields["hash"] = hash_of(fields)
            conn.execute(
                "INSERT INTO trace.call (run, seq, evaluation_plugin, connection, door, started_at, ended_at, request,"
                " outcome, answer, error, prev_hash, hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s,"
                " %s::jsonb, %s::jsonb, %s, %s)",
                (run, fields["seq"], evaluation_plugin, connection, door, started_at, ended_at, texts[0],
                 outcome, texts[1], texts[2], fields["prev_hash"], fields["hash"]))
    return fields


def calls(pid, run: str) -> list[dict]:
    """A run's calls in this project, in order, as exported (the fields the hash covers, and the hash)."""
    with projectdb.connect(pid) as conn:
        rows = conn.execute(
            "SELECT seq, connection, door, started_at, ended_at, request, outcome, answer, error, prev_hash, hash"
            " FROM trace.call WHERE run = %s ORDER BY seq", (run,)).fetchall()
    return [{**r, "started_at": _iso(r["started_at"]), "ended_at": _iso(r["ended_at"])} for r in rows]


def seqs_with_text(pid, evaluation_plugin: str, sha256: str) -> list[int]:
    """The seq of each call of that test whose request or answer holds a JSON string with this SHA-256 digest
    (of its UTF-8 text): where a measure's trace reference (`trace:<test>#sha256=<digest>`) leads."""
    if not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
        return []
    with projectdb.connect(pid) as conn:
        rows = conn.execute(
            "SELECT c.seq FROM trace.call c WHERE c.evaluation_plugin = %s::uuid AND EXISTS ("
            " SELECT 1 FROM jsonb_path_query(jsonb_build_array(c.request, coalesce(c.answer, 'null'::jsonb)),"
            "  'strict $.**') v"
            " WHERE jsonb_typeof(v) = 'string'"
            "  AND encode(sha256(convert_to(v #>> '{}', 'UTF8')), 'hex') = %s)"
            " ORDER BY c.run, c.seq", (str(evaluation_plugin), sha256)).fetchall()
    return [r["seq"] for r in rows]


def export(pid, run: str) -> str:
    """JSON lines: one per call, then {"seal": {"calls": n, "digest": the last hash or null}}."""
    rows = calls(pid, run)
    if not rows:
        return empty_export()
    lines = [json.dumps(r, ensure_ascii=False) for r in rows]
    lines.append(json.dumps({"seal": {"calls": len(rows), "digest": rows[-1]["hash"]}}))
    return "\n".join(lines) + "\n"


def seal(pid, run: str) -> dict:
    """{"calls", "digest"} of a run's trace in this project, as its export ends: the count and the last hash."""
    with projectdb.connect(pid) as conn:
        row = conn.execute("SELECT count(*) AS calls, (array_agg(hash ORDER BY seq DESC))[1] AS digest"
                           " FROM trace.call WHERE run = %s", (run,)).fetchone()
    return {"calls": row["calls"], "digest": row["digest"]}


def empty_export() -> str:
    return json.dumps({"seal": {"calls": 0, "digest": None}}) + "\n"


def verify(lines: list[dict]) -> bool:
    """Whether exported lines are a whole, unedited chain: each hash recomputes, each row names the one
    before it, seq counts from 1, and the seal gives the count and the last hash."""
    calls_, seals = [x for x in lines if "seal" not in x], [x["seal"] for x in lines if "seal" in x]
    if len(seals) != 1:
        return False
    prev = None
    for i, call in enumerate(calls_, start=1):
        if call.get("seq") != i or call.get("prev_hash") != prev or hash_of(call) != call.get("hash"):
            return False
        prev = call["hash"]
    return seals[0] == {"calls": len(calls_), "digest": prev}
