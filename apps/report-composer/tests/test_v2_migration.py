"""Migration 0005 of report run v2 on a database made before the run (R-D.1, R-D.2, R-U2.4, R-C.3).

A bed of its own (aisc-t-composer-mig-*, core seed only): migrations 0001 to 0004 run first, as the
composer ran them before this run; layouts, a template and a generated report are written in the old
shapes; then the app starts and its migrate runs 0005. Never the host's 5432.
"""
import json
import shutil
from pathlib import Path

import pytest

from conftest import FIXED_NOW, IDS, ISSUER, ORIGIN, lazily, need, report_bed
from v2_fakes import FakeRendererV2

pytestmark = [pytest.mark.db]
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
M0005 = MIGRATIONS / "0005_presets_and_document_settings.sql"

TEMPLATE = "70000000-0000-4000-8000-0000000000a1"
LAYOUT_1 = "10000000-0000-4000-8000-0000000000a1"
LAYOUT_2 = "10000000-0000-4000-8000-0000000000a2"
REPORT = "20000000-0000-4000-8000-0000000000a1"
LINKS_1 = [{"objective_id": "R1.1", "tests": ["LangBiTe"], "checklists": ["cl-1"]}]
LINKS_2 = [{"objective_id": "R2.1", "tests": [], "checklists": ["cl-2"]}]
OLD_PDF = b"%PDF-1.7\n% made before the run\n%%EOF\n"
BLOCKS_1 = [
    ("30000000-0000-4000-8000-000000000001", 0, "cover", {"report_title": "Old report"}),
    ("30000000-0000-4000-8000-000000000002", 1, "free_text", {"text": "plain\ntext"}),
    ("30000000-0000-4000-8000-000000000003", 2, "summary_coverage", {"links": LINKS_1, "show_uncovered_only": False}),
    ("30000000-0000-4000-8000-000000000004", 3, "summary_coverage", {"links": LINKS_2, "show_uncovered_only": True}),
]
BLOCKS_2 = [("30000000-0000-4000-8000-000000000011", 0, "summary_coverage", {"links": []}),
            ("30000000-0000-4000-8000-000000000012", 1, "ai_card", {})]


def _q(v) -> str:
    return "'" + json.dumps(v).replace("'", "''") + "'"


def _old_rows(bed):
    rw = "report_composer_rw"
    bed.psql("platform", f"""
        INSERT INTO report_composer.template (id, project_id, name, font, font_size_pt, primary_color, accent_color,
            created_by, updated_by, updated_at)
        VALUES ('{TEMPLATE}', '{IDS["A"]}', 'Old look', 'liberation-serif', 11, '#123456', '#abcdef', 'alice', 'alice',
                '2026-09-01 10:00+00');
        INSERT INTO report_composer.layout (id, project_id, system_id, name, revision, created_by, updated_by, updated_at,
            template_id)
        VALUES ('{LAYOUT_1}', '{IDS["A"]}', '{IDS["A_V2"]}', 'Old layout', 7, 'alice', 'alice', '2026-09-02 10:00+00',
                '{TEMPLATE}'),
               ('{LAYOUT_2}', '{IDS["A"]}', '{IDS["A_V2"]}', 'No links', 3, 'alice', 'alice', '2026-09-03 10:00+00',
                NULL);
        INSERT INTO report_composer.generated_report (id, layout_id, layout_revision, project_id, system_id, snapshot,
            status, pdf, sha256, size_bytes, created_by, finished_at)
        VALUES ('{REPORT}', '{LAYOUT_1}', 7, '{IDS["A"]}', '{IDS["A_V2"]}', '{{"mode": "pdf"}}', 'done',
                decode('{OLD_PDF.hex()}', 'hex'), 'x', {len(OLD_PDF)}, 'alice', now());
    """, role=rw)
    values = ",".join(f"('{lid}', '{iid}', {pos}, '{t}', {_q(o)})"
                      for lid, blocks in ((LAYOUT_1, BLOCKS_1), (LAYOUT_2, BLOCKS_2)) for iid, pos, t, o in blocks)
    bed.psql("platform", "INSERT INTO report_composer.layout_block (layout_id, instance_id, position, block_type,"
                         f" options) VALUES {values};", role=rw)


@pytest.fixture(scope="module")
def mig(key, tmp_path_factory):
    """(bed, client, renderer) after 0001-0004, the old rows, and the app's own start (0005)."""
    report_bed.check_dsn_env()
    bed = report_bed.build("composer-mig", modules=False)
    mp = pytest.MonkeyPatch()
    opened = []
    try:
        url = bed.dsn("report_composer_rw", "platform")
        old_dir = tmp_path_factory.mktemp("old-migrations")
        for f in sorted(MIGRATIONS.glob("000[1-4]_*.sql")):
            shutil.copy(f, old_dir / f.name)
        from report_composer import db
        from report_composer.migrate import migrate

        with db.connect(url) as conn:
            migrate(conn, directory=old_dir)
        _old_rows(bed)
        mp.setenv("AUTH_ENABLED", "true")
        mp.setenv("KEYCLOAK_ISSUER", ISSUER)
        mp.setenv("KEYCLOAK_JWKS_URL", "http://keycloak:8080/unused-in-tests")
        mp.setenv("PLATFORM_ORIGIN", ORIGIN)
        mp.setenv("REPORT_COMPOSER_DATABASE_URL", url)
        import aisc_identity.service

        mp.setattr(aisc_identity.service, "key_for_jwks", lambda u: (lambda _t: key.public_key()))
        renderer = FakeRendererV2()
        from fastapi.testclient import TestClient

        def build():
            app = need("report_composer.app", "create_app")(database_url=url, renderer=renderer,
                                                              clock=lambda: FIXED_NOW)
            c = TestClient(app, base_url="http://localhost")
            c.__enter__()
            opened.append(c)
            return c

        yield bed, lazily(build), renderer
    finally:
        for c in opened:
            c.__exit__(None, None, None)
        mp.undo()
        bed.stop()


def row(bed, sql):
    out = bed.scalar("platform", f"SELECT row_to_json(t)::text FROM ({sql}) t")
    return json.loads(out) if out else None


# ── R-D.2 static: the migration touches only the composer's schema ──────────

def test_r_d_2_0005_touches_only_report_composer():
    assert M0005.exists(), "missing feature: migrations/0005_presets_and_document_settings.sql"
    sql = M0005.read_text()
    import re

    for m in re.finditer(r"\b(ALTER\s+TABLE|CREATE\s+TABLE|UPDATE|INSERT\s+INTO|DELETE\s+FROM|DROP\s+TABLE)\s+"
                         r"(IF\s+(?:NOT\s+)?EXISTS\s+)?([\w.\"]+)", sql, re.I):
        assert m.group(3).startswith("report_composer."), m.group(0)
    assert not re.search(r"\bGRANT\b", sql, re.I)
    assert not re.search(r"\bDROP\s+(TABLE|COLUMN)\b", sql, re.I), "0005 is additive only"


# ── R-D.1 the columns and the preset table ──────────────────────────────────

def test_r_d_1_new_columns_with_their_defaults(mig):
    bed, client, _ = mig
    client.get("/api/block-types")
    cols = json.loads(bed.scalar("platform", "SELECT coalesce(jsonb_object_agg(table_name || '.' || column_name,"
                                             " coalesce(column_default, 'NULL') || '|' || is_nullable), '{}')::text"
                                             " FROM information_schema.columns WHERE table_schema = 'report_composer'"))
    expect = {"layout.language": ("'en'", "NO"), "layout.toc": ("'auto'", "NO"), "layout.numbering": ("false", "NO"),
              "layout.coverage": ("'[]'", "NO"), "template.header_text": (None, "YES"),
              "template.footer_text": (None, "YES"), "template.marking": ("'none'", "NO"),
              "template.show_document_id": ("false", "NO"), "generated_report.format": ("'pdf'", "NO"),
              "generated_report.fingerprint": (None, "YES")}
    for col, (default, nullable) in expect.items():
        assert col in cols, f"missing feature: column report_composer.{col}"
        got_default, got_null = cols[col].rsplit("|", 1)
        assert got_null == nullable, col
        if default:
            assert got_default.startswith(default), (col, got_default)
    for col in ("id", "name", "description", "language", "toc", "numbering", "blocks", "source_project_id",
                "created_by", "created_at"):
        assert f"preset.{col}" in cols, f"missing feature: column report_composer.preset.{col}"


@pytest.mark.parametrize("sql", [
    f"UPDATE report_composer.layout SET toc = 'sometimes' WHERE id = '{LAYOUT_2}'",
    f"UPDATE report_composer.layout SET language = 'english' WHERE id = '{LAYOUT_2}'",
    f"UPDATE report_composer.layout SET coverage = '{{}}' WHERE id = '{LAYOUT_2}'",
    f"UPDATE report_composer.template SET marking = 'secret' WHERE id = '{TEMPLATE}'",
    f"UPDATE report_composer.template SET header_text = repeat('x', 121) WHERE id = '{TEMPLATE}'",
    f"UPDATE report_composer.generated_report SET format = 'odt' WHERE id = '{REPORT}'",
    "INSERT INTO report_composer.preset (name, blocks, created_by) VALUES ('', '[]', 'alice')",
])
def test_r_d_1_checks_refuse_bad_values(mig, sql):
    bed, client, _ = mig
    client.get("/api/block-types")
    assert M0005.exists(), "missing feature: migration 0005"
    r = bed.psql("platform", "BEGIN; " + sql + "; ROLLBACK;", role="report_composer_rw", check=False)
    assert r.returncode != 0 and "violates check constraint" in r.stderr, r.stderr[-300:]


def test_r_d_1_preset_names_are_unique(mig):
    bed, client, _ = mig
    client.get("/api/block-types")
    r = bed.psql("platform", "BEGIN; INSERT INTO report_composer.preset (name, blocks, created_by) VALUES"
                             " ('Same', '[]', 'a'), ('Same', '[]', 'b'); ROLLBACK;", role="report_composer_rw",
                 check=False)
    assert r.returncode != 0 and ("unique" in r.stderr or "duplicate key" in r.stderr), r.stderr[-300:]


# ── R-U2.4 the coverage map moves out of the first summary block ────────────

def test_r_u2_4_the_lowest_summary_links_become_the_layout_map(mig):
    bed, client, _ = mig
    client.get("/api/block-types")
    got = row(bed, f"SELECT coverage, revision, updated_at FROM report_composer.layout WHERE id = '{LAYOUT_1}'")
    assert got.get("coverage") == LINKS_1, "missing feature: coverage moved by 0005"
    assert got["revision"] == 7 and got["updated_at"].startswith("2026-09-02T10:00:00")
    links = json.loads(bed.scalar("platform", "SELECT jsonb_object_agg(position, options->'links')::text FROM"
                                              f" report_composer.layout_block WHERE layout_id = '{LAYOUT_1}'"
                                              " AND block_type = 'summary_coverage'"))
    assert links == {"2": [], "3": LINKS_2}


def test_r_u2_4_a_layout_without_links_keeps_an_empty_map(mig):
    bed, client, _ = mig
    client.get("/api/block-types")
    got = row(bed, f"SELECT coverage, revision FROM report_composer.layout WHERE id = '{LAYOUT_2}'")
    assert got.get("coverage") == [] and got["revision"] == 3


# ── R-C.3 old layouts, templates and reports ────────────────────────────────

def test_r_c_3_an_old_layout_previews_with_the_same_snapshot_apart_from_new_keys(mig, auth):
    bed, client, renderer = mig
    r = client.get(f"/api/p/alpha/layouts/{LAYOUT_1}/preview", headers=auth("alice"))
    assert r.status_code == 200
    sent = renderer.snapshots[-1]
    assert sent.get("coverage_links") == LINKS_1, "missing feature: coverage_links from the moved map"
    old = {"project_id": IDS["A"], "system_id": IDS["A_V2"],
           "layout": {"id": LAYOUT_1, "name": "Old layout", "revision": 7},
           "blocks": [{"instance_id": iid, "block_type": t, "options": o} for iid, _, t, o in BLOCKS_1],
           "mode": "preview", "requested_by": "alice",
           "style": {"font": "liberation-serif", "font_size_pt": 11, "primary_color": "#123456",
                     "accent_color": "#abcdef"}}
    old["blocks"][2]["options"] = {**old["blocks"][2]["options"], "links": []}     # moved to the map (R-U2.4)
    new_keys = {"snapshot_version", "language", "document", "coverage_links"}
    stripped = {k: v for k, v in sent.items() if k not in new_keys}
    stripped["style"] = {k: v for k, v in stripped["style"].items()
                         if k not in ("header_text", "footer_text", "marking", "show_document_id")}
    assert stripped == old
    assert sent.get("language", "en") == "en"
    assert (sent.get("document") or {}).get("toc", "auto") == "auto"
    assert (sent.get("document") or {}).get("numbering", False) is False


def test_r_c_3_templates_keep_their_look(mig, auth):
    bed, client, _ = mig
    t = next(x for x in client.get("/api/p/alpha/templates", headers=auth("alice")).json() if x["id"] == TEMPLATE)
    assert (t["font"], t["font_size_pt"], t["primary_color"], t["accent_color"]) == \
        ("liberation-serif", 11, "#123456", "#abcdef")
    assert (t.get("marking"), t.get("show_document_id"), t.get("header_text", "absent")) == ("none", False, None)


def test_r_c_3_stored_reports_download_unchanged(mig, auth):
    bed, client, _ = mig
    r = client.get(f"/api/p/alpha/reports/{REPORT}/pdf", headers=auth("victor"))
    assert r.status_code == 200 and r.content == OLD_PDF
    d = client.get(f"/api/p/alpha/reports/{REPORT}/download", headers=auth("victor"))
    assert d.status_code == 200 and d.content == OLD_PDF and d.headers["content-type"] == "application/pdf"
    assert bed.scalar("platform", f"SELECT format FROM report_composer.generated_report WHERE id = '{REPORT}'") == "pdf"
