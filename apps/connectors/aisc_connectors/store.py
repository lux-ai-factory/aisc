"""SQL for the connector records. Every function opens its own short transaction."""
from __future__ import annotations

import uuid

import psycopg
from psycopg.types.json import Jsonb

from aisc_connectors import db

_COLUMNS = ("pid, project_pid, ai_system_pid, name, slug, kind, environment, auth, settings, chat,"
            " is_target_access, import_warnings, created_at, updated_at")
_JSON = {"auth", "settings", "chat", "document", "import_warnings"}
_UPDATABLE = {"name", "slug", "kind", "environment", "document", "import_warnings",
              "auth", "settings", "chat", "is_target_access"}

_SLUG_CONSTRAINT = "connector_project_pid_slug_key"
_TARGET_ACCESS_INDEX = "one_target_access_per_project"


class DuplicateName(ValueError):
    """A connector with this (project_pid, slug) already exists."""


def _insert(project_pid, ai_system_pid, name, slug, kind, environment, created_by, *, compute_target_access):
    # is_target_access is computed inside the INSERT, not by a SELECT before it, so concurrent
    # creates for the same project cannot both see "no target access yet" in between. If two such
    # INSERTs land at the same instant, the partial unique index one_target_access_per_project
    # catches the loser, and create_connector retries it once with false.
    is_target_sql = ("NOT EXISTS (SELECT 1 FROM connector.connector WHERE project_pid = %s AND is_target_access)"
                      if compute_target_access else "false")
    params: list[object] = [uuid.uuid4(), project_pid, ai_system_pid, name, slug, kind, environment]
    if compute_target_access:
        params.append(project_pid)
    params.append(created_by)
    with db.pool().connection() as conn:
        return conn.execute(
            f"INSERT INTO connector.connector (pid, project_pid, ai_system_pid, name, slug, kind, environment,"
            f" is_target_access, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, {is_target_sql}, %s)"
            f" RETURNING {_COLUMNS}",
            params,
        ).fetchone()


def create_connector(project_pid, ai_system_pid, name, slug, kind, environment, created_by) -> dict:
    try:
        return _insert(project_pid, ai_system_pid, name, slug, kind, environment, created_by,
                       compute_target_access=True)
    except psycopg.errors.UniqueViolation as exc:
        if exc.diag.constraint_name == _SLUG_CONSTRAINT:
            raise DuplicateName("a connector with this name already exists in the project") from exc
        if exc.diag.constraint_name == _TARGET_ACCESS_INDEX:
            # Lost the race for target access between our NOT EXISTS check and the INSERT: someone
            # else's connector already claimed it, so this one is not the target-access connector.
            return _insert(project_pid, ai_system_pid, name, slug, kind, environment, created_by,
                           compute_target_access=False)
        raise


def get(connector_pid, with_document: bool = False) -> dict | None:
    columns = _COLUMNS + (", document" if with_document else "")
    with db.pool().connection() as conn:
        return conn.execute(f"SELECT {columns} FROM connector.connector WHERE pid = %s",
                            (connector_pid,)).fetchone()


def list_for_project(project_pid) -> list[dict]:
    with db.pool().connection() as conn:
        return conn.execute(
            f"SELECT {_COLUMNS} FROM connector.connector WHERE project_pid = %s ORDER BY created_at",
            (project_pid,),
        ).fetchall()


def update(connector_pid, **fields) -> dict:
    unknown = set(fields) - _UPDATABLE
    if unknown:
        raise ValueError(f"cannot update columns {sorted(unknown)}")
    sets = ", ".join(f"{k} = %s" for k in fields) + ", updated_at = now()"
    values = [Jsonb(v) if k in _JSON and v is not None else v for k, v in fields.items()]
    with db.pool().connection() as conn:
        try:
            return conn.execute(
                f"UPDATE connector.connector SET {sets} WHERE pid = %s RETURNING {_COLUMNS}",
                (*values, connector_pid),
            ).fetchone()
        except psycopg.errors.UniqueViolation as exc:
            if exc.diag.constraint_name == _SLUG_CONSTRAINT:
                raise DuplicateName("a connector with this name already exists in the project") from exc
            raise


def delete(connector_pid) -> None:
    with db.pool().connection() as conn:
        conn.execute("DELETE FROM connector.connector WHERE pid = %s", (connector_pid,))


def make_target_access(connector_pid) -> None:
    with db.pool().connection() as conn:
        project = conn.execute("SELECT project_pid FROM connector.connector WHERE pid = %s",
                               (connector_pid,)).fetchone()["project_pid"]
        # Lock every row of the project before the two UPDATEs below, so a concurrent
        # make_target_access/create_connector for the same project serializes behind this one
        # instead of interleaving with it.
        conn.execute("SELECT pid FROM connector.connector WHERE project_pid = %s FOR UPDATE", (project,))
        conn.execute("UPDATE connector.connector SET is_target_access = false"
                     " WHERE project_pid = %s AND is_target_access", (project,))
        conn.execute("UPDATE connector.connector SET is_target_access = true WHERE pid = %s", (connector_pid,))


def target_access_count(project_pid) -> int:
    with db.pool().connection() as conn:
        return conn.execute(
            "SELECT count(*) AS n FROM connector.connector WHERE project_pid = %s AND is_target_access",
            (project_pid,),
        ).fetchone()["n"]
