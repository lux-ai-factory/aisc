"""The composer's SQL.

Every helper takes a connection first. The version, layout, template and report helpers take a
connection to ONE project's database (projectdb.ProjectDatabases.connect): the database is the project,
so no row carries or filters by a project column; they read project.system and write only the schema
report_composer. The preset helpers take a connection to `platform` and use the install-wide library
report_library. A malformed uuid argument finds nothing.
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

#: a layout's document settings before anyone sets them (project migration 0003 turns numbering on for
#: existing layouts too). The layout table's coverage column is neither read nor written: the links are set
#: in step 4.
DEFAULT_SETTINGS = {"show_index": True, "numbering": True}


def layout_names(conn) -> set[str]:
    return {r["name"] for r in conn.execute("SELECT name FROM report_composer.layout WHERE deleted_at IS NULL").fetchall()}


def list_layouts(conn) -> list[dict]:
    return conn.execute(
        "SELECT l.id::text AS id, l.name, l.description,"
        " l.revision, l.updated_at, lr.last_report, l.template_id::text AS template_id, t.name AS template_name"
        " FROM report_composer.layout l"
        " LEFT JOIN report_composer.template t ON t.id = l.template_id"
        " LEFT JOIN LATERAL (SELECT json_build_object('id', r.id, 'created_at', r.created_at, 'status', r.status)"
        "                    AS last_report FROM report_composer.generated_report r WHERE r.layout_id = l.id"
        "                    ORDER BY r.created_at DESC LIMIT 1) lr ON true"
        " WHERE l.deleted_at IS NULL ORDER BY l.name").fetchall()


def get_layout(conn, layout_id, for_update=False) -> dict | None:
    lid = _uuid(layout_id)
    if lid is None:
        return None
    row = conn.execute(
        "SELECT l.id::text AS id, l.name, l.description,"
        " l.template_id::text AS template_id, l.revision, l.created_at,"
        " l.created_by, l.updated_at, l.updated_by, l.show_index, l.numbering"
        " FROM report_composer.layout l WHERE l.id = %s AND l.deleted_at IS NULL"
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


def insert_layout(conn, *, template_id, name, description, blocks, who, now, settings=None) -> str:
    s = {**DEFAULT_SETTINGS, **(settings or {})}
    row = conn.execute(
        "INSERT INTO report_composer.layout (template_id, name, description, created_at,"
        " created_by, updated_at, updated_by, show_index, numbering)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text AS id",
        (template_id, name, description, now, who, now, who, s["show_index"],
         s["numbering"])).fetchone()
    _insert_blocks(conn, row["id"], blocks)
    keep_revision(conn, row["id"], now)
    return row["id"]


def keep_revision(conn, layout_id, now) -> None:
    """The layout's revision as saved, kept for good (layout_revision is append-only)."""
    from .ledger import layout_state

    state = layout_state(get_layout(conn, layout_id))
    conn.execute("INSERT INTO report_composer.layout_revision (layout_id, revision, state, saved_at)"
                 " VALUES (%s, %s, %s, %s)", (layout_id, state["revision"], Jsonb(state), now))


def update_layout(conn, layout_id, *, based_on, name, description, template_id, blocks, who,
                  now, settings) -> int | None:
    row = conn.execute(
        "UPDATE report_composer.layout SET revision = revision + 1, name = %s, description = %s,"
        " template_id = %s, updated_at = %s, updated_by = %s, show_index = %s, numbering = %s"
        " WHERE id = %s AND revision = %s RETURNING revision",
        (name, description, template_id, now, who, settings["show_index"],
         settings["numbering"], layout_id, based_on)).fetchone()
    if row is None:
        return None
    conn.execute("DELETE FROM report_composer.layout_block WHERE layout_id = %s", (layout_id,))
    _insert_blocks(conn, layout_id, blocks)
    keep_revision(conn, layout_id, now)
    return row["revision"]


def delete_layout(conn, layout_id, now) -> bool:
    """Deletes a layout as the user sees it: it is hidden, and its reports stay."""
    lid = _uuid(layout_id)
    if lid is None:
        return False
    return conn.execute("UPDATE report_composer.layout SET deleted_at = %s WHERE id = %s AND deleted_at IS NULL"
                        " RETURNING id", (now, lid)).fetchone() is not None


def deleted_layouts_with_reports(conn) -> list[dict]:
    """The deleted layouts that have reports, newest deletion first, each with its reports (no bytes)."""
    return conn.execute(
        "SELECT l.id::text AS id, l.name, l.deleted_at,"
        " json_agg(json_build_object('id', r.id, 'status', r.status, 'format', r.format, 'created_at', r.created_at,"
        "                            'has_pdf', coalesce(r.format, 'pdf') = 'pdf' OR r.pdf_copy IS NOT NULL)"
        "          ORDER BY r.created_at DESC) AS reports"
        " FROM report_composer.layout l JOIN report_composer.generated_report r ON r.layout_id = l.id"
        " WHERE l.deleted_at IS NOT NULL GROUP BY l.id ORDER BY l.deleted_at DESC, l.name").fetchall()


# Templates (a report's look)

_TEMPLATE = ("id::text AS id, name, font, font_size_pt::float8 AS font_size_pt, primary_color, accent_color,"
             " logo IS NOT NULL AS has_logo, created_at, created_by, updated_at, header_text, footer_text, marking,"
             " show_document_id")


def list_templates(conn) -> list[dict]:
    return conn.execute(f"SELECT {_TEMPLATE} FROM report_composer.template ORDER BY name").fetchall()


def get_template(conn, template_id, with_logo=False, for_update=False) -> dict | None:
    tid = _uuid(template_id)
    if tid is None:
        return None
    extra = ", logo_mime, logo" if with_logo else ""
    lock = " FOR UPDATE" if for_update else ""
    return conn.execute(f"SELECT {_TEMPLATE}{extra} FROM report_composer.template WHERE id = %s{lock}",
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


def layouts_using(conn, template_id) -> list[str]:
    """The layouts (deleted ones too) drawn in a template, locked: its delete is about to change them."""
    tid = _uuid(template_id)
    if tid is None:
        return []
    return [r["id"] for r in conn.execute("SELECT id::text AS id FROM report_composer.layout WHERE template_id = %s"
                                          " ORDER BY id FOR UPDATE", (tid,)).fetchall()]


def drop_template_from(conn, layout_id, *, who, now) -> int:
    """A layout leaves its template (being deleted) as a save would: its next revision, kept. Returns that
    revision."""
    row = conn.execute("UPDATE report_composer.layout SET template_id = NULL, revision = revision + 1,"
                       " updated_at = %s, updated_by = %s WHERE id = %s RETURNING revision",
                       (now, who, layout_id)).fetchone()
    if conn.execute("SELECT deleted_at IS NULL AS live FROM report_composer.layout WHERE id = %s",
                    (layout_id,)).fetchone()["live"]:
        keep_revision(conn, layout_id, now)
    return row["revision"]


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
                  fmt="pdf", report_id=None, period_from=None, period_to=None, other_versions=False,
                  compare_to=None) -> str:
    return conn.execute(
        "INSERT INTO report_composer.generated_report (id, layout_id, layout_revision, system_id,"
        " snapshot, status, created_by, created_at, format, period_from, period_to, other_versions, compare_to)"
        " VALUES (coalesce(%s::uuid, gen_random_uuid()), %s, %s, %s, %s, 'running', %s, %s, %s, %s, %s, %s, %s)"
        " RETURNING id::text AS id",
        (report_id, layout_id, layout_revision, system_id, Jsonb(snapshot), created_by, created_at,
         fmt, period_from, period_to, other_versions, compare_to)).fetchone()["id"]


def finish_report(conn, report_id, *, status, finished_at, pdf=None, sha256=None, size_bytes=None,
                  block_statuses=(), error_ref=None, error_code=None, fingerprint=None, pdf_copy=None,
                  pdf_copy_sha256=None) -> None:
    """`pdf` holds the document in its own format; `pdf_copy` a Word report's PDF from the same generation."""
    conn.execute(
        "UPDATE report_composer.generated_report SET status = %s, pdf = %s, sha256 = %s, size_bytes = %s,"
        " block_statuses = %s, error_ref = %s, error_code = %s, finished_at = %s, fingerprint = %s,"
        " pdf_copy = %s, pdf_copy_sha256 = %s WHERE id = %s",
        (status, pdf, sha256, size_bytes, Jsonb(list(block_statuses)), error_ref, error_code, finished_at,
         fingerprint, pdf_copy, pdf_copy_sha256, report_id))


def list_reports(conn, layout_id) -> list[dict]:
    return conn.execute("SELECT r.id::text AS id, r.layout_revision, r.status, r.created_at, r.created_by,"
                        " r.size_bytes, r.format, r.fingerprint, r.sha256, s.number AS system_number,"
                        " r.period_from, r.period_to, r.other_versions, c.number AS compare_number,"
                        " (r.pdf IS NOT NULL AND (coalesce(r.format, 'pdf') = 'pdf' OR r.pdf_copy IS NOT NULL))"
                        " AS has_pdf"
                        " FROM report_composer.generated_report r"
                        " LEFT JOIN project.system s ON s.pid = r.system_id"
                        " LEFT JOIN project.system c ON c.pid = r.compare_to"
                        " WHERE r.layout_id = %s ORDER BY r.created_at DESC, r.id",
                        (layout_id,)).fetchall()


def reports_of(conn, layout_id) -> list[dict]:
    """What a layout's reports are, without their bytes (what a layout's delete takes with it)."""
    return conn.execute("SELECT id::text AS id, status, format, sha256, layout_revision, system_id::text AS system_id,"
                        " created_at FROM report_composer.generated_report WHERE layout_id = %s"
                        " ORDER BY created_at, id", (layout_id,)).fetchall()


def get_report(conn, report_id) -> dict | None:
    rid = _uuid(report_id)
    if rid is None:
        return None
    return conn.execute(
        "SELECT r.id::text AS id, r.status, r.pdf, r.snapshot, r.created_at, s.number AS system_number, r.format,"
        " r.sha256, r.pdf_copy, r.pdf_copy_sha256"
        " FROM report_composer.generated_report r"
        " LEFT JOIN project.system s ON s.pid = r.system_id"
        " WHERE r.id = %s", (rid,)).fetchone()


# Saved presets: the install-wide library, on a connection to `platform`; no route uses it

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
