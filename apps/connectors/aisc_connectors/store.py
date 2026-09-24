"""SQL for the connector records. Every function opens its own short transaction."""
from __future__ import annotations

import uuid

from psycopg.types.json import Jsonb

from aisc_connectors import db

_COLUMNS = ("pid, project_pid, ai_system_pid, name, slug, kind, environment, auth, settings, chat,"
            " is_target_access, import_warnings, created_at, updated_at")
_JSON = {"auth", "settings", "chat", "document", "import_warnings"}


def create_connector(project_pid, ai_system_pid, name, slug, kind, environment, created_by) -> dict:
    with db.pool().connection() as conn:
        first = conn.execute(
            "SELECT NOT EXISTS (SELECT 1 FROM connector.connector WHERE project_pid = %s AND is_target_access)"
            " AS first", (project_pid,),
        ).fetchone()["first"]
        return conn.execute(
            f"INSERT INTO connector.connector (pid, project_pid, ai_system_pid, name, slug, kind, environment,"
            f" is_target_access, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {_COLUMNS}",
            (uuid.uuid4(), project_pid, ai_system_pid, name, slug, kind, environment, first, created_by),
        ).fetchone()


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
    sets = ", ".join(f"{k} = %s" for k in fields) + ", updated_at = now()"
    values = [Jsonb(v) if k in _JSON and v is not None else v for k, v in fields.items()]
    with db.pool().connection() as conn:
        return conn.execute(
            f"UPDATE connector.connector SET {sets} WHERE pid = %s RETURNING {_COLUMNS}",
            (*values, connector_pid),
        ).fetchone()


def delete(connector_pid) -> None:
    with db.pool().connection() as conn:
        conn.execute("DELETE FROM connector.connector WHERE pid = %s", (connector_pid,))


def make_target_access(connector_pid) -> None:
    with db.pool().connection() as conn:
        project = conn.execute("SELECT project_pid FROM connector.connector WHERE pid = %s",
                               (connector_pid,)).fetchone()["project_pid"]
        conn.execute("UPDATE connector.connector SET is_target_access = false"
                     " WHERE project_pid = %s AND is_target_access", (project,))
        conn.execute("UPDATE connector.connector SET is_target_access = true WHERE pid = %s", (connector_pid,))


def target_access_count(project_pid) -> int:
    with db.pool().connection() as conn:
        return conn.execute(
            "SELECT count(*) AS n FROM connector.connector WHERE project_pid = %s AND is_target_access",
            (project_pid,),
        ).fetchone()["n"]
