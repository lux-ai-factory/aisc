"""Numbering is on by default, retroactively (2026-10-01): a new layout numbers its report, every layout and
saved preset stored before this numbers its report too (project migration 0003, library migration 0002),
and the built-in layouts all number. The Numbering box stays, so an editor can still turn it off."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import BLOCK_TYPES
from isolation_fixtures import iso_bed, iso_clean, iso_make_client, new_project, project_db_template  # noqa: F401
from v2_fakes import FakeRendererV2

APP = Path(__file__).resolve().parents[1]
PROJECT_MIGRATION = APP / "migrations/project/0003_numbering_on.sql"
LIBRARY_MIGRATION = APP / "migrations/library/0002_presets_numbered.sql"


def test_a_layout_without_settings_numbers():
    from report_composer.settings import document_settings, snapshot_document
    assert document_settings({}, None)["numbering"] is True
    assert snapshot_document({}, None)["numbering"] is True


def test_the_new_layout_editor_starts_with_numbering_on():
    from report_composer.pages import EMPTY_LAYOUT
    assert EMPTY_LAYOUT["numbering"] is True


def test_every_built_in_layout_numbers():
    from report_composer import builtin_layouts
    assert {l["id"]: l["numbering"] for l in builtin_layouts.all_layouts(BLOCK_TYPES)} == \
        {builtin_layouts.PREFIX + s: True for s in builtin_layouts.ORDER}


def test_a_preset_file_without_numbering_exports_and_applies_numbered():
    from report_composer import presets
    p = presets.Preset(id=None, name="No setting", blocks=[])
    assert presets.export_doc(p)["numbering"] is True
    assert presets.from_layout({"name": "L", "blocks": []}, BLOCK_TYPES).numbering is True


def test_the_migrations_switch_numbering_on_for_what_is_stored():
    project = PROJECT_MIGRATION.read_text(encoding="utf-8")
    assert "SET DEFAULT true" in project and "UPDATE report_composer.layout SET numbering = true" in project
    library = LIBRARY_MIGRATION.read_text(encoding="utf-8")
    assert "UPDATE report_library.preset SET numbering = true" in library


@pytest.mark.db
def test_a_layout_saved_with_numbering_off_is_numbered_after_the_migration(iso_bed, iso_make_client, auth):
    """A project database migrated up to 0002 with a layout stored with numbering false: 0003 turns it on
    and makes true the column default."""
    from report_composer.migrate import migrate_project
    import psycopg

    client = iso_make_client(FakeRendererV2())
    client.get("/api/block-types")
    db = new_project(iso_bed, "9b000000-0000-4000-8000-0000000000aa", "numbered-later")
    assert client.get("/api/p/numbered-later/layouts", headers=auth("alice")).status_code == 200  # migrates it
    iso_bed.psql(db, "DELETE FROM report_composer.schema_migration WHERE name = '0003_numbering_on.sql';"
                     " ALTER TABLE report_composer.layout ALTER COLUMN numbering SET DEFAULT false;"
                     " INSERT INTO report_composer.layout (name, created_by, updated_by, numbering)"
                     " VALUES ('Old one', 'alice', 'alice', false);")
    dsn = project_db_template(iso_bed).format(database=db)
    with psycopg.connect(dsn) as conn:
        assert migrate_project(conn) == ["0003_numbering_on.sql"]
    assert iso_bed.scalar(db, "SELECT numbering FROM report_composer.layout WHERE name = 'Old one'") == "t"
    assert iso_bed.scalar(db, "SELECT column_default FROM information_schema.columns WHERE table_schema ="
                              " 'report_composer' AND table_name = 'layout' AND column_name = 'numbering'") == "true"
