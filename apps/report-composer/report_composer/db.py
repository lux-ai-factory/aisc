"""The composer's SQL (report run 2026-09-23, 01 section 3.1, D13).

Every helper takes a connection first. It reads core.project, core.system and core.project_member
and writes only its own schema report_composer. A malformed uuid argument finds nothing.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


@contextmanager
def connect(database_url):
    """One transaction per `with`: committed at the end, rolled back on an exception."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        yield conn


def _uuid(value) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


# ── versions ─────────────────────────────────────────────────────────────────

def systems(conn, project_pid) -> list[dict]:
    return conn.execute("SELECT pid::text AS pid, number, name, version AS release FROM core.system"
                        " WHERE project_id = %s ORDER BY number DESC", (project_pid,)).fetchall()


def system_of_project(conn, project_pid, system_pid) -> dict | None:
    s = _uuid(system_pid)
    if s is None:
        return None
    return conn.execute("SELECT pid::text AS pid, number, name, version AS release FROM core.system"
                        " WHERE project_id = %s AND pid = %s", (project_pid, s)).fetchone()


def latest_system(conn, project_pid) -> dict | None:
    return conn.execute("SELECT pid::text AS pid, number, name, version AS release FROM core.system"
                        " WHERE project_id = %s ORDER BY number DESC LIMIT 1", (project_pid,)).fetchone()


# ── layouts ──────────────────────────────────────────────────────────────────

def list_layouts(conn, project_pid) -> list[dict]:
    return conn.execute(
        "SELECT l.id::text AS id, l.name, l.description, l.system_id::text AS system_id, s.number AS system_number,"
        " l.revision, l.updated_at, lr.last_report, l.template_id::text AS template_id, t.name AS template_name"
        " FROM report_composer.layout l JOIN core.system s ON s.pid = l.system_id"
        " LEFT JOIN report_composer.template t ON t.id = l.template_id"
        " LEFT JOIN LATERAL (SELECT json_build_object('id', r.id, 'created_at', r.created_at, 'status', r.status)"
        "                    AS last_report FROM report_composer.generated_report r WHERE r.layout_id = l.id"
        "                    ORDER BY r.created_at DESC LIMIT 1) lr ON true"
        " WHERE l.project_id = %s ORDER BY l.name", (project_pid,)).fetchall()


def get_layout(conn, project_pid, layout_id, for_update=False) -> dict | None:
    lid = _uuid(layout_id)
    if lid is None:
        return None
    row = conn.execute(
        "SELECT l.id::text AS id, l.project_id::text AS project_id, l.name, l.description,"
        " l.system_id::text AS system_id, l.template_id::text AS template_id, l.revision, l.created_at,"
        " l.created_by, l.updated_at, l.updated_by"
        " FROM report_composer.layout l WHERE l.id = %s AND l.project_id = %s"
        + (" FOR UPDATE" if for_update else ""), (lid, project_pid)).fetchone()
    if row is None:
        return None
    row["blocks"] = [dict(b) for b in conn.execute(
        "SELECT instance_id::text AS instance_id, block_type, options FROM report_composer.layout_block"
        " WHERE layout_id = %s ORDER BY position", (lid,)).fetchall()]
    return row


def _insert_blocks(conn, layout_id, blocks) -> None:
    for i, b in enumerate(blocks):
        conn.execute("INSERT INTO report_composer.layout_block (layout_id, instance_id, position, block_type, options)"
                     " VALUES (%s, %s, %s, %s, %s)",
                     (layout_id, b["instance_id"], i, b["block_type"], Jsonb(b.get("options") or {})))


def insert_layout(conn, *, project_pid, system_pid, template_id, name, description, blocks, who, now) -> str:
    row = conn.execute(
        "INSERT INTO report_composer.layout (project_id, system_id, template_id, name, description, created_at,"
        " created_by, updated_at, updated_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text AS id",
        (project_pid, system_pid, template_id, name, description, now, who, now, who)).fetchone()
    _insert_blocks(conn, row["id"], blocks)
    return row["id"]


def update_layout(conn, layout_id, *, based_on, name, description, system_pid, template_id, blocks, who,
                  now) -> int | None:
    row = conn.execute(
        "UPDATE report_composer.layout SET revision = revision + 1, name = %s, description = %s, system_id = %s,"
        " template_id = %s, updated_at = %s, updated_by = %s WHERE id = %s AND revision = %s RETURNING revision",
        (name, description, system_pid, template_id, now, who, layout_id, based_on)).fetchone()
    if row is None:
        return None
    conn.execute("DELETE FROM report_composer.layout_block WHERE layout_id = %s", (layout_id,))
    _insert_blocks(conn, layout_id, blocks)
    return row["revision"]


def delete_layout(conn, project_pid, layout_id) -> bool:
    lid = _uuid(layout_id)
    if lid is None:
        return False
    return conn.execute("DELETE FROM report_composer.layout WHERE id = %s AND project_id = %s RETURNING id",
                        (lid, project_pid)).fetchone() is not None


# ── templates (a report's look) ──────────────────────────────────────────────

_TEMPLATE = ("id::text AS id, name, font, font_size_pt::float8 AS font_size_pt, primary_color, accent_color,"
             " logo IS NOT NULL AS has_logo, created_at, created_by, updated_at")


def list_templates(conn, project_pid) -> list[dict]:
    return conn.execute(f"SELECT {_TEMPLATE} FROM report_composer.template WHERE project_id = %s ORDER BY name",
                        (project_pid,)).fetchall()


def get_template(conn, project_pid, template_id, with_logo=False) -> dict | None:
    tid = _uuid(template_id)
    if tid is None:
        return None
    extra = ", logo_mime, logo" if with_logo else ""
    return conn.execute(f"SELECT {_TEMPLATE}{extra} FROM report_composer.template WHERE id = %s AND project_id = %s",
                        (tid, project_pid)).fetchone()


def template_names(conn, project_pid) -> set[str]:
    return {r["name"] for r in conn.execute("SELECT name FROM report_composer.template WHERE project_id = %s",
                                            (project_pid,)).fetchall()}


def insert_template(conn, *, project_pid, look, logo, who, now) -> str:
    mime, raw = logo if logo else (None, None)
    return conn.execute(
        "INSERT INTO report_composer.template (project_id, name, font, font_size_pt, primary_color, accent_color,"
        " logo_mime, logo, created_at, created_by, updated_at, updated_by)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text AS id",
        (project_pid, look["name"], look["font"], look["font_size_pt"], look["primary_color"], look["accent_color"],
         mime, raw, now, who, now, who)).fetchone()["id"]


def update_template(conn, project_pid, template_id, *, look, logo, who, now) -> bool:
    mime, raw = logo if logo else (None, None)
    return conn.execute(
        "UPDATE report_composer.template SET name = %s, font = %s, font_size_pt = %s, primary_color = %s,"
        " accent_color = %s, logo_mime = %s, logo = %s, updated_at = %s, updated_by = %s"
        " WHERE id = %s AND project_id = %s RETURNING id",
        (look["name"], look["font"], look["font_size_pt"], look["primary_color"], look["accent_color"], mime, raw,
         now, who, template_id, project_pid)).fetchone() is not None


def delete_template(conn, project_pid, template_id) -> bool:
    tid = _uuid(template_id)
    if tid is None:
        return False
    return conn.execute("DELETE FROM report_composer.template WHERE id = %s AND project_id = %s RETURNING id",
                        (tid, project_pid)).fetchone() is not None


# ── generated reports ────────────────────────────────────────────────────────

def running_report(conn, layout_id, since) -> bool:
    return conn.execute("SELECT 1 FROM report_composer.generated_report WHERE layout_id = %s AND status = 'running'"
                        " AND created_at > %s", (layout_id, since)).fetchone() is not None


def insert_report(conn, *, layout_id, layout_revision, project_id, system_id, snapshot, created_by, created_at) -> str:
    return conn.execute(
        "INSERT INTO report_composer.generated_report (layout_id, layout_revision, project_id, system_id, snapshot,"
        " status, created_by, created_at) VALUES (%s, %s, %s, %s, %s, 'running', %s, %s) RETURNING id::text AS id",
        (layout_id, layout_revision, project_id, system_id, Jsonb(snapshot), created_by, created_at)).fetchone()["id"]


def finish_report(conn, report_id, *, status, finished_at, pdf=None, sha256=None, size_bytes=None,
                  block_statuses=(), error_ref=None, error_code=None) -> None:
    conn.execute(
        "UPDATE report_composer.generated_report SET status = %s, pdf = %s, sha256 = %s, size_bytes = %s,"
        " block_statuses = %s, error_ref = %s, error_code = %s, finished_at = %s WHERE id = %s",
        (status, pdf, sha256, size_bytes, Jsonb(list(block_statuses)), error_ref, error_code, finished_at, report_id))


def list_reports(conn, layout_id) -> list[dict]:
    return conn.execute("SELECT id::text AS id, layout_revision, status, created_at, created_by, size_bytes"
                        " FROM report_composer.generated_report WHERE layout_id = %s ORDER BY created_at DESC, id",
                        (layout_id,)).fetchall()


def get_report(conn, project_pid, report_id) -> dict | None:
    rid = _uuid(report_id)
    if rid is None:
        return None
    return conn.execute(
        "SELECT r.id::text AS id, r.status, r.pdf, r.snapshot, r.created_at, s.number AS system_number"
        " FROM report_composer.generated_report r JOIN report_composer.layout l ON l.id = r.layout_id"
        " LEFT JOIN core.system s ON s.pid = r.system_id"
        " WHERE r.id = %s AND l.project_id = %s", (rid, project_pid)).fetchone()
