"""Deleting a run, and the stored files a deletion leaves behind.

An owner deletes a run (DELETE /projects/{slug}/runs/{evaluation}); the retention sweep deletes old runs the
same way. In one transaction on the project's database:

- `engine.purge_evaluation` removes the run's measures, observations and artifact rows and marks the run
  purged (its row stays), and names the stored artifact files and the run's tests;
- `trace.purge_runs` removes those tests' recorded calls, keeping a tombstone per run with the number of calls
  and the chain's last hash;
- the artifact files are removed from the shared bucket; a file the store would not remove (or no store at
  all) is kept in core.leftover_object with its project, and `retry_leftovers` tries it again;
- the ledger event `run.purged` names what went, the trace digests and what remained.

Both functions are SECURITY DEFINER, owned by the schema owner roles: the platform's runtime role cannot remove
a measure or a recorded call any other way. The files go before the commit, so the event can name the ones that
stayed. A commit that then fails leaves the run's rows with fewer files; deleting the run again finishes it.
"""
from __future__ import annotations

import json
import logging
import os

from platform_service import db, projectdb, proof_store
from platform_service.ledger import outbox

logger = logging.getLogger(__name__)


class NoSuchRun(LookupError):
    """The project's engine has no run with this id."""


class EngineNotReady(RuntimeError):
    """The project's database has no purge function yet: the engine has not migrated it."""


def artifacts_bucket() -> str:
    return os.environ.get("S3_ARTIFACTS_BUCKET", "").strip() or "artifacts"


def remove_files(pid, bucket: str, names: list[str]) -> list[str]:
    """Remove the project's files from a shared bucket; the names it kept, each recorded in
    core.leftover_object. Never raises."""
    if not names:
        return []
    kept = list(names)
    store = proof_store.store()
    if store is not None:
        try:
            kept = list(store.remove_objects(bucket, list(names)))
        except Exception:                                               # noqa: BLE001
            logger.warning("project %s: %d files of bucket %s could not be removed", pid, len(names), bucket,
                           exc_info=True)
    else:
        logger.warning("project %s: no store is set up (S3_URL), so %d files of bucket %s wait for the sweep",
                       pid, len(names), bucket)
    if kept:
        _remember(pid, bucket, kept)
    return kept


def _remember(pid, bucket: str, names: list[str]) -> None:
    try:
        with db.pool().connection() as conn:
            for name in names:
                conn.execute("INSERT INTO core.leftover_object (pid, bucket, name) VALUES (%s, %s, %s)"
                             " ON CONFLICT (bucket, name) DO NOTHING", (str(pid), bucket, name))
    except Exception:                                                   # noqa: BLE001
        logger.exception("project %s: files left in bucket %s could not be recorded; remove them by hand: %s",
                         pid, bucket, ", ".join(names))


def leftover_objects() -> list[tuple[str, str]]:
    """(bucket, name) of every file still waiting to be removed."""
    with db.pool().connection() as conn:
        return [(r["bucket"], r["name"]) for r in conn.execute(
            "SELECT bucket, name FROM core.leftover_object ORDER BY first_failed_at, bucket, name")]


def retry_leftovers() -> int:
    """Try again to remove every recorded leftover file; how many went."""
    store = proof_store.store()
    if store is None:
        return 0
    with db.pool().connection() as conn:
        rows = conn.execute("SELECT bucket, name FROM core.leftover_object").fetchall()
    by_bucket: dict[str, list[str]] = {}
    for row in rows:
        by_bucket.setdefault(row["bucket"], []).append(row["name"])
    removed = 0
    for bucket, names in by_bucket.items():
        try:
            kept = set(store.remove_objects(bucket, names))
        except Exception:                                               # noqa: BLE001
            logger.warning("the leftover files of bucket %s could not be removed yet", bucket, exc_info=True)
            continue
        gone = [n for n in names if n not in kept]
        if gone:
            with db.pool().connection() as conn:
                conn.execute("DELETE FROM core.leftover_object WHERE bucket = %s AND name = ANY(%s)", (bucket, gone))
            removed += len(gone)
    return removed


def purge_run(pid, evaluation_pid: str, by: str, reason: str) -> dict:
    """Delete one run of the project. Returns {"artifacts": n, "measures": n, "calls": n,
    "trace_digests": {run: hash}, "leftover_objects": [names]}. NoSuchRun, EngineNotReady."""
    with projectdb.connect(pid, row_factory=None) as conn:
        with conn.transaction():
            if conn.execute("SELECT to_regprocedure('engine.purge_evaluation(uuid)')").fetchone()[0] is None:
                raise EngineNotReady(f"project {pid}: the engine has not migrated its database yet")
            engine = conn.execute("SELECT engine.purge_evaluation(%s::uuid)", (str(evaluation_pid),)).fetchone()[0]
            if engine is None:
                raise NoSuchRun(str(evaluation_pid))
            trace = conn.execute("SELECT trace.purge_runs(%s::uuid[], %s, %s)",
                                 (engine["evaluation_plugins"], by, reason)).fetchone()[0]
            names = list(engine["artifacts"])
            kept = remove_files(pid, artifacts_bucket(), names)
            out = {"artifacts": len(names), "measures": int(engine["measures"]), "calls": int(trace["calls"]),
                   "trace_digests": dict(trace["trace_digests"]), "leftover_objects": kept}
            details = {"reason": reason, **out}
            outbox.emit_project(conn, "run.purged", item_type="evaluation", item_id=str(evaluation_pid),
                                details=details, content=json.loads(json.dumps(details)))
    logger.info("project %s: run %s deleted by %s (%s): %s", pid, evaluation_pid, by, reason, out)
    return out
