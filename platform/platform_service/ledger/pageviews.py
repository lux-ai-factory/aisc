"""Page views and browser-reported moments: kept in Postgres, never in immudb, for
PAGE_VIEW_RETENTION. Who sent the beacon is certain (its request is witnessed); what it says is the
browser's word, so every row reads `reported_by=browser`."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace


class AlreadyUsed(Exception):
    """This witnessed request already carried a beacon."""


def record(project_pid: str, actor_ref: str, action: str, details: dict, request_id: str | None) -> None:
    from psycopg import errors

    from platform_service import db

    with db.pool().connection() as conn:
        try:
            conn.execute("INSERT INTO ledger.page_view (project_pid, actor_ref, action, details, request_id)"
                         " VALUES (%s, %s, %s, %s, %s)", (project_pid, actor_ref, action, json.dumps(details), request_id))
        except errors.UniqueViolation:
            raise AlreadyUsed(request_id) from None


def recent(project_pid: str, limit: int = 100) -> list:
    from platform_service import db

    with db.pool().connection() as conn:
        rows = conn.execute("SELECT action, actor_ref, details, at FROM ledger.page_view WHERE project_pid = %s"
                            " ORDER BY at DESC LIMIT %s", (project_pid, limit)).fetchall()
    return [SimpleNamespace(**dict(r), reported_by="browser") for r in rows]


def expire(older_than: timedelta) -> int:
    """Delete what is older than `older_than` (the retention, run daily)."""
    from platform_service import db

    with db.pool().connection() as conn:
        return conn.execute("DELETE FROM ledger.page_view WHERE at < %s",
                            (datetime.now(timezone.utc) - older_than,)).rowcount
