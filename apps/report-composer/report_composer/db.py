"""The composer's SQL (isolation 2026-09-25, 01-specs.md I8.1, I8.3).

Every helper takes a connection first. The version, layout, template and report helpers take a
connection to ONE project's database (projectdb.ProjectDatabases.connect): the database is the project,
so no row carries or filters by a project column; they read project.system and write only the schema
report_composer. The preset helpers take a connection to `platform` and use the install-wide library
report_library (D4). A malformed uuid argument finds nothing.
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


# Versions

_SYSTEM = "pid::text AS pid, number, name, version AS release"


def systems(conn) -> list[dict]:
    return conn.execute(f"SELECT {_SYSTEM} FROM project.system ORDER BY number DESC").fetchall()


def system_of_project(conn, system_pid) -> dict | None:
    """The version, when it is one of this database's project."""
    s = _uuid(system_pid)
    if s is None:
        return None
    return conn.execute(f"SELECT {_SYSTEM} FROM project.system WHERE pid = %s", (s,)).fetchone()


def latest_system(conn) -> dict | None:
    return conn.execute(f"SELECT {_SYSTEM} FROM project.system ORDER BY number DESC LIMIT 1").fetchone()


# Layouts

#: a layout's document settings and coverage map before anyone sets them (today's behaviour)
DEFAULT_SETTINGS = {"toc": "auto", "numbering": False, "coverage": []}


def layout_names(conn) -> set[str]:
    return {r["name"] for r in conn.execute("SELECT name FROM report_composer.layout").fetchall()}


def list_layouts(conn) -> list[dict]:
    return conn.execute(
        "SELECT l.id::text AS id, l.name, l.description, l.system_id::text AS system_id, s.number AS system_number,"
        " l.revision, l.updated_at, lr.last_report, l.template_id::text AS template_id, t.name AS template_name"
        " FROM report_composer.layout l JOIN project.system s ON s.pid = l.system_id"
        " LEFT JOIN report_composer.template t ON t.id = l.template_id"
        " LEFT JOIN LATERAL (SELECT json_build_object('id', r.id, 'created_at', r.created_at, 'status', r.status)"
        "                    AS last_report FROM report_composer.generated_report r WHERE r.layout_id = l.id"
        "                    ORDER BY r.created_at DESC LIMIT 1) lr ON true"
        " ORDER BY l.name").fetchall()


def get_layout(conn, layout_id, for_update=False) -> dict | None:
    lid = _uuid(layout_id)
    if lid is None:
        return None
    row = conn.execute(
        "SELECT l.id::text AS id, l.name, l.description,"
        " l.system_id::text AS system_id, l.template_id::text AS template_id, l.revision, l.created_at,"
        " l.created_by, l.updated_at, l.updated_by, l.toc, l.numbering, l.coverage"
        " FROM report_composer.layout l WHERE l.id = %s"
        + (" FOR UPDATE" if for_update else ""), (lid,)).fetchone()
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


def insert_layout(conn, *, system_pid, template_id, name, description, blocks, who, now,
                  settings=None) -> str:
    s = {**DEFAULT_SETTINGS, **(settings or {})}
    row = conn.execute(
        "INSERT INTO report_composer.layout (system_id, template_id, name, description, created_at,"
        " created_by, updated_at, updated_by, toc, numbering, coverage)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text AS id",
        (system_pid, template_id, name, description, now, who, now, who, s["toc"],
         s["numbering"], Jsonb(s["coverage"]))).fetchone()
    _insert_blocks(conn, row["id"], blocks)
    return row["id"]


def update_layout(conn, layout_id, *, based_on, name, description, system_pid, template_id, blocks, who,
                  now, settings) -> int | None:
    row = conn.execute(
        "UPDATE report_composer.layout SET revision = revision + 1, name = %s, description = %s, system_id = %s,"
        " template_id = %s, updated_at = %s, updated_by = %s, toc = %s, numbering = %s,"
        " coverage = %s WHERE id = %s AND revision = %s RETURNING revision",
        (name, description, system_pid, template_id, now, who, settings["toc"],
         settings["numbering"], Jsonb(settings["coverage"]), layout_id, based_on)).fetchone()
    if row is None:
        return None
    conn.execute("DELETE FROM report_composer.layout_block WHERE layout_id = %s", (layout_id,))
    _insert_blocks(conn, layout_id, blocks)
    return row["revision"]


def delete_layout(conn, layout_id) -> bool:
    lid = _uuid(layout_id)
    if lid is None:
        return False
    return conn.execute("DELETE FROM report_composer.layout WHERE id = %s RETURNING id", (lid,)).fetchone() is not None


# Templates (a report's look)

_TEMPLATE = ("id::text AS id, name, font, font_size_pt::float8 AS font_size_pt, primary_color, accent_color,"
             " logo IS NOT NULL AS has_logo, created_at, created_by, updated_at, header_text, footer_text, marking,"
             " show_document_id")


def list_templates(conn) -> list[dict]:
    return conn.execute(f"SELECT {_TEMPLATE} FROM report_composer.template ORDER BY name").fetchall()


def get_template(conn, template_id, with_logo=False) -> dict | None:
    tid = _uuid(template_id)
    if tid is None:
        return None
    extra = ", logo_mime, logo" if with_logo else ""
    return conn.execute(f"SELECT {_TEMPLATE}{extra} FROM report_composer.template WHERE id = %s",
                        (tid,)).fetchone()


def template_names(conn) -> set[str]:
    return {r["name"] for r in conn.execute("SELECT name FROM report_composer.template").fetchall()}


def _look_values(look) -> tuple:
    return (look["name"], look["font"], look["font_size_pt"], look["primary_color"], look["accent_color"],
            look.get("header_text"), look.get("footer_text"), look.get("marking", "none"),
            bool(look.get("show_document_id", False)))


def insert_template(conn, *, look, logo, who, now) -> str:
    mime, raw = logo if logo else (None, None)
    return conn.execute(
        "INSERT INTO report_composer.template (name, font, font_size_pt, primary_color, accent_color,"
        " header_text, footer_text, marking, show_document_id, logo_mime, logo, created_at, created_by, updated_at,"
        " updated_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text AS id",
        (*_look_values(look), mime, raw, now, who, now, who)).fetchone()["id"]


def update_template(conn, template_id, *, look, logo, who, now) -> bool:
    mime, raw = logo if logo else (None, None)
    return conn.execute(
        "UPDATE report_composer.template SET name = %s, font = %s, font_size_pt = %s, primary_color = %s,"
        " accent_color = %s, header_text = %s, footer_text = %s, marking = %s, show_document_id = %s,"
        " logo_mime = %s, logo = %s, updated_at = %s, updated_by = %s"
        " WHERE id = %s RETURNING id",
        (*_look_values(look), mime, raw, now, who, template_id)).fetchone() is not None


def delete_template(conn, template_id) -> bool:
    tid = _uuid(template_id)
    if tid is None:
        return False
    return conn.execute("DELETE FROM report_composer.template WHERE id = %s RETURNING id",
                        (tid,)).fetchone() is not None


# Generated reports

def running_report(conn, layout_id, since) -> bool:
    return conn.execute("SELECT 1 FROM report_composer.generated_report WHERE layout_id = %s AND status = 'running'"
                        " AND created_at > %s", (layout_id, since)).fetchone() is not None


def insert_report(conn, *, layout_id, layout_revision, system_id, snapshot, created_by, created_at,
                  fmt="pdf", report_id=None) -> str:
    return conn.execute(
        "INSERT INTO report_composer.generated_report (id, layout_id, layout_revision, system_id,"
        " snapshot, status, created_by, created_at, format)"
        " VALUES (coalesce(%s::uuid, gen_random_uuid()), %s, %s, %s, %s, 'running', %s, %s, %s)"
        " RETURNING id::text AS id",
        (report_id, layout_id, layout_revision, system_id, Jsonb(snapshot), created_by, created_at,
         fmt)).fetchone()["id"]


def finish_report(conn, report_id, *, status, finished_at, pdf=None, sha256=None, size_bytes=None,
                  block_statuses=(), error_ref=None, error_code=None, fingerprint=None) -> None:
    conn.execute(
        "UPDATE report_composer.generated_report SET status = %s, pdf = %s, sha256 = %s, size_bytes = %s,"
        " block_statuses = %s, error_ref = %s, error_code = %s, finished_at = %s, fingerprint = %s WHERE id = %s",
        (status, pdf, sha256, size_bytes, Jsonb(list(block_statuses)), error_ref, error_code, finished_at,
         fingerprint, report_id))


def list_reports(conn, layout_id) -> list[dict]:
    return conn.execute("SELECT id::text AS id, layout_revision, status, created_at, created_by, size_bytes,"
                        " format, fingerprint, sha256"
                        " FROM report_composer.generated_report WHERE layout_id = %s ORDER BY created_at DESC, id",
                        (layout_id,)).fetchall()


def get_report(conn, report_id) -> dict | None:
    rid = _uuid(report_id)
    if rid is None:
        return None
    return conn.execute(
        "SELECT r.id::text AS id, r.status, r.pdf, r.snapshot, r.created_at, s.number AS system_number, r.format"
        " FROM report_composer.generated_report r"
        " LEFT JOIN project.system s ON s.pid = r.system_id"
        " WHERE r.id = %s", (rid,)).fetchone()


# Saved presets: the install-wide library, on a connection to `platform` (D4)

_PRESET = ("id::text AS id, name, description, toc, numbering, blocks, source_project_id::text AS"
           " source_project_id, created_by, created_at")


def list_presets(conn) -> list[dict]:
    return conn.execute(f"SELECT {_PRESET} FROM report_library.preset ORDER BY name").fetchall()


def get_preset(conn, preset_id) -> dict | None:
    pid = _uuid(preset_id)
    if pid is None:
        return None
    return conn.execute(f"SELECT {_PRESET} FROM report_library.preset WHERE id = %s", (pid,)).fetchone()


def preset_names(conn) -> set[str]:
    return {r["name"] for r in conn.execute("SELECT name FROM report_library.preset").fetchall()}


def insert_preset(conn, *, name, description, toc, numbering, blocks, source_project_id, who, now) -> str:
    return conn.execute(
        "INSERT INTO report_library.preset (name, description, toc, numbering, blocks,"
        " source_project_id, created_by, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        " RETURNING id::text AS id",
        (name, description, toc, numbering, Jsonb(blocks), source_project_id, who, now)).fetchone()["id"]


def delete_preset(conn, preset_id) -> bool:
    pid = _uuid(preset_id)
    if pid is None:
        return False
    return conn.execute("DELETE FROM report_library.preset WHERE id = %s RETURNING id", (pid,)).fetchone() is not None
