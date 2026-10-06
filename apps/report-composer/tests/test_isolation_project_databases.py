"""The composer on one database per project.

Static tests on the source and migrations, and database tests on the bed of isolation_fixtures.py
(no report_composer schema and no core.system in `platform`; one database per project).
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import pytest

from conftest import error_code, new_layout, new_template, put_layout
from isolation_fixtures import (IDS, LOCK, MODULE_TABLES, iso_bed, iso_clean, iso_make_client, new_project,  # noqa: F401
                                pdb, spy, tables_named, unique)
from v2_fakes import FakeRendererV2, v2blk

APP = Path(__file__).resolve().parents[1]
SRC = APP / "report_composer"
MIGRATIONS = APP / "migrations"
PROJECT_BASELINE = MIGRATIONS / "project" / "0001_project_database.sql"
LIBRARY_BASELINE = MIGRATIONS / "library" / "0001_presets.sql"
A, B, E = IDS["A"], IDS["B"], IDS["E"]


def _read(path: Path) -> str:
    if not path.exists():
        pytest.fail(f"missing feature: {path.relative_to(APP)} (I8.2)", pytrace=False)
    return path.read_text(encoding="utf-8")


def _sql_only(text: str) -> str:
    """The SQL without its -- comments (a comment may name tables a test looks for)."""
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


# the migrations are split


def test_i8_2_the_project_baseline_makes_the_four_tables_without_core_or_project_id():
    """layout, layout_block, template, generated_report as the shared schema had them, minus
    project_id, with the version keys on project.system(pid) (NO ACTION)."""
    sql = _sql_only(_read(PROJECT_BASELINE))
    for table in MODULE_TABLES:
        assert re.search(rf"CREATE TABLE\s+(IF NOT EXISTS\s+)?report_composer\.{table}\b", sql, re.I), table
    assert "core." not in sql, "the project baseline names the shared core schema"
    assert "project_id" not in sql, "the project baseline still has a project_id column"
    assert len(re.findall(r"REFERENCES\s+project\.system\s*\(\s*pid\s*\)", sql, re.I)) >= 2, \
        "layout.system_id and generated_report.system_id must reference project.system(pid)"
    assert not re.search(r"REFERENCES\s+project\.system\s*\(\s*pid\s*\)\s*ON DELETE", sql, re.I), \
        "the version keys keep NO ACTION (I1.6)"
    assert "preset" not in sql.lower(), "presets are the library's (D4), not a project's"


def test_i8_2_the_library_migration_makes_report_library_preset_without_a_key():
    """report_library.preset with source_project_id uuid NULL and no foreign key."""
    sql = _sql_only(_read(LIBRARY_BASELINE))
    assert re.search(r"CREATE TABLE\s+(IF NOT EXISTS\s+)?report_library\.preset\b", sql, re.I)
    assert re.search(r"source_project_id\s+uuid\b(?![^,\n]*NOT NULL)", sql, re.I), "source_project_id uuid NULL"
    assert "REFERENCES" not in sql.upper(), "the library holds no key into a project (D4)"
    assert "core." not in sql and "report_composer." not in sql


def test_i8_2_i8_6_the_project_baseline_is_schema_only():
    """The baseline writes no rows: existing rows arrive by the platform's data move, so no data step
    is repeated here."""
    sql = _sql_only(_read(PROJECT_BASELINE))
    assert not re.search(r"^\s*(INSERT\s+INTO|UPDATE\s+\w|DELETE\s+FROM)", sql, re.I | re.M), \
        "the project baseline must not carry a data step"


def test_i8_2_no_old_migration_is_left_for_the_platform_database():
    """migrations/ holds only migrations/project/ and migrations/library/: no file migrates the
    shared `platform` schema."""
    left = sorted(p.name for p in MIGRATIONS.glob("*.sql"))
    assert not left, f"old-layout migrations still at the top of migrations/: {left}"
    assert (MIGRATIONS / "project").is_dir() and (MIGRATIONS / "library").is_dir()


def test_i8_4_the_runner_keeps_its_lock_number():
    """Lock 8_190_233_707 in each database (library and every project)."""
    source = (SRC / "migrate.py").read_text(encoding="utf-8")
    assert "8_190_233_707" in source or "8190233707" in source
    assert "library" in source and "project" in source, "migrate.py knows both histories"


# never another module's schema


def test_i8_5_the_composer_names_no_other_modules_schema():
    """In its source the composer names only report_composer, report_library,
    project.system and, for the access SQL, core.project and core.project_member."""
    hits = []
    for p in SRC.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        for m in re.finditer(r"\b(core|qualification|control_objectives|engine|controls|llm|provision)\.([a-z_]+)\b",
                             text):
            if m.group(1) == "core" and m.group(2) in ("project", "project_member"):
                continue
            hits.append(f"{p.name}: {m.group(0)}")
    assert not hits, hits


def test_i8_1_the_source_reads_the_project_database_template():
    """REPORT_COMPOSER_PROJECT_DATABASE_URL is read by the app (the compose wiring is pinned in
    scripts/tests/test_compose_isolation.py)."""
    assert any("REPORT_COMPOSER_PROJECT_DATABASE_URL" in p.read_text(encoding="utf-8") for p in SRC.rglob("*.py"))


# database tests on the bed

@pytest.fixture
def iso_client(iso_make_client):
    return iso_make_client(FakeRendererV2())


def _names(bed, db, sql):
    out = bed.scalar(db, sql)
    return sorted(x for x in (out or "").split(",") if x)


@pytest.mark.db
def test_i8_4_start_migrates_the_library_and_every_project_database(iso_client, iso_bed):
    """At start the library (platform) and every project database are at their heads; `platform`
    gets no report_composer schema."""
    iso_client.get("/api/block-types")
    assert _names(iso_bed, "platform", "SELECT string_agg(name, ',') FROM report_library.schema_migration") \
        == ["0001_presets.sql", "0002_presets_numbered.sql"]
    assert iso_bed.scalar("platform", "SELECT to_regclass('report_library.preset') IS NOT NULL") == "t"
    assert iso_bed.scalar("platform", "SELECT count(*) FROM pg_namespace WHERE nspname = 'report_composer'") == "0"
    for key in ("A", "B", "E"):
        db = pdb(IDS[key])
        assert _names(iso_bed, db, "SELECT string_agg(name, ',') FROM report_composer.schema_migration") \
            == ["0001_project_database.sql", "0002_layouts_without_data.sql", "0003_numbering_on.sql",
               "0004_layout_revisions.sql", "0005_layouts_soft_deleted.sql",
               "0006_pdf_copy.sql", "0007_builtin_reports.sql"], key
        for t in MODULE_TABLES:
            assert iso_bed.scalar(db, f"SELECT to_regclass('report_composer.{t}') IS NOT NULL") == "t", (key, t)


@pytest.mark.db
def test_i8_2_i1_7_the_project_tables_have_no_project_id_and_keys_on_project_system(iso_client, iso_bed):
    """No project_id in layout, template, generated_report; the report's version keys
    (system_id, compare_to) reference project.system(pid) with NO ACTION, and a layout has none;
    layout_block and generated_report follow their layout."""
    iso_client.get("/api/block-types")
    db = pdb(A)
    cols = _names(iso_bed, db, "SELECT string_agg(table_name || '.' || column_name, ',') FROM"
                               " information_schema.columns WHERE table_schema = 'report_composer'"
                               " AND column_name = 'project_id'")
    assert cols == [], cols
    keys = iso_bed.scalar(db, "SELECT string_agg(conrelid::regclass::text || '>' || confrelid::regclass::text || ':'"
                              " || confdeltype, ',' ORDER BY 1) FROM pg_constraint WHERE contype = 'f'"
                              " AND connamespace = 'report_composer'::regnamespace"
                              " AND confrelid = 'project.system'::regclass")
    assert set(keys.split(",")) == {"report_composer.generated_report>project.system:a"}, keys


@pytest.mark.db
def test_i2_6_no_reader_reads_the_composers_tables(iso_client, iso_bed):
    """report_composer is on the reader list with `none` for report_ro and dashboard_ro."""
    iso_client.get("/api/block-types")
    for reader in ("report_ro", "dashboard_ro"):
        for t in MODULE_TABLES:
            got = iso_bed.scalar(pdb(A), f"SELECT has_table_privilege('{reader}', 'report_composer.{t}', 'SELECT')")
            assert got == "f", (reader, t)


@pytest.mark.db
@pytest.mark.usefixtures("iso_clean")
def test_i8_1_a_projects_layouts_live_in_its_own_database(iso_client, iso_bed, auth):
    """A template and a layout made in alpha are rows of alpha's database only."""
    t = new_template(iso_client, auth, slug="alpha", name=unique("Look"))
    lay = new_layout(iso_client, auth, slug="alpha", template_id=t["id"], system_id=IDS["A_V2"])
    assert iso_bed.scalar(pdb(A), f"SELECT count(*) FROM report_composer.layout WHERE id = '{lay['id']}'") == "1"
    assert iso_bed.scalar(pdb(A), f"SELECT count(*) FROM report_composer.template WHERE id = '{t['id']}'") == "1"
    for other in (B, E):
        assert iso_bed.scalar(pdb(other), "SELECT count(*) FROM report_composer.layout") == "0"
        assert iso_bed.scalar(pdb(other), "SELECT count(*) FROM report_composer.template") == "0"


@pytest.mark.db
@pytest.mark.usefixtures("iso_clean")
def test_i8_1_the_platform_connection_reads_only_core_and_the_library(iso_client, auth, spy):
    """Over REPORT_COMPOSER_DATABASE_URL only core.project, core.project_member and report_library.*;
    everything of the project (its versions, layouts, templates, reports) over its own database."""
    spy["reset"]()
    t = new_template(iso_client, auth, slug="alpha", name=unique("Look"))
    lay = new_layout(iso_client, auth, slug="alpha", template_id=t["id"], system_id=IDS["A_V2"],
                     blocks=[v2blk("cover")])
    assert iso_client.get("/api/p/alpha/systems", headers=auth("alice")).status_code == 200
    r = iso_client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"system_id": IDS["A_V2"]}, headers=auth("alice"))
    assert r.status_code in (200, 201), r.text[:300]
    on_platform, on_alpha = set(), set()
    for db, sql in spy["sql"]:
        (on_platform if db == "platform" else on_alpha if db == pdb(A) else set()).update(tables_named(sql))
    allowed = {"core.project", "core.project_member", "report_library.preset", "report_library.schema_migration"}
    assert on_platform <= allowed, on_platform - allowed
    assert {"project.system", "report_composer.layout", "report_composer.template",
            "report_composer.generated_report"} <= on_alpha, on_alpha


@pytest.mark.db
@pytest.mark.parametrize("who,method,path,status", [
    ("bob", "get", "/api/p/alpha/layouts", 404),                      # a stranger
    ("victor", "post", "/api/p/alpha/layouts", 403),                  # a viewer writing
    ("alice", "get", "/api/p/no-such-project/layouts", 404),          # no such project
    ("alice", "get", "/api/p/gamma/layouts", 404),                    # a project without a database
])
def test_i8_1_the_guard_decides_before_a_project_database_is_opened(iso_client, auth, spy, who, method, path,
                                                                    status):
    """A project database is opened only after guards.guard has decided membership for that pid."""
    iso_client.get("/api/block-types")
    spy["reset"]()
    kw = {"json": {"name": "x"}} if method == "post" else {}
    r = getattr(iso_client, method)(path, headers=auth(who), **kw)
    assert r.status_code == status, r.text[:300]
    opened = {db for db, _ in spy["connections"] if db.startswith("project_") and db != pdb(IDS["C"])}
    if status == 403 or who == "bob":
        assert opened == set(), f"a project database was opened before the guard refused: {opened}"


@pytest.mark.db
@pytest.mark.usefixtures("iso_clean")
def test_i8_3_a_version_of_another_project_is_422_system_not_in_project(iso_client, auth):
    """Every system_id names a row of project.system of the same database: Beta's version chosen for
    an Alpha report (and as the version to compare with) is 422. The report holds the version, not
    the layout."""
    t = new_template(iso_client, auth, slug="alpha", name=unique("Look"))
    lay = new_layout(iso_client, auth, slug="alpha", template_id=t["id"], blocks=[v2blk("cover")])
    r = iso_client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"system_id": IDS["B_V1"]},
                        headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "system_not_in_project", r.text[:300]
    r = iso_client.post(f"/api/p/alpha/layouts/{lay['id']}/reports",
                        json={"system_id": IDS["A_V2"], "compare_to": IDS["B_V1"]}, headers=auth("alice"))
    assert r.status_code == 422, r.text[:300]
    r = iso_client.get(f"/api/p/alpha/choices?block_type=test_results&system_id={IDS['B_V1']}", headers=auth("alice"))
    assert r.status_code in (404, 422), r.text[:300]


@pytest.mark.db
def test_i8_3_the_versions_are_those_of_the_projects_database(iso_client, auth):
    """GET systems lists project.system of alpha's database, newest first."""
    r = iso_client.get("/api/p/alpha/systems", headers=auth("alice"))
    assert r.status_code == 200, r.text[:300]
    assert [s["number"] for s in r.json()] == [3, 2, 1]
    assert {s["pid"] for s in r.json()} == {IDS["A_V1"], IDS["A_V2"], IDS["A_V3"]}


@pytest.mark.db
@pytest.mark.usefixtures("iso_clean")
def test_i8_3_a_generated_report_names_a_version_of_its_database(iso_client, iso_bed, auth):
    """The report row is in alpha's database and its system_id resolves in the same database."""
    lay = new_layout(iso_client, auth, slug="alpha", system_id=IDS["A_V2"], blocks=[v2blk("cover")])
    r = iso_client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"system_id": IDS["A_V2"]}, headers=auth("alice"))
    assert r.status_code in (200, 201), r.text[:300]
    assert iso_bed.scalar(pdb(A), "SELECT count(*) FROM report_composer.generated_report r JOIN project.system s"
                                  f" ON s.pid = r.system_id WHERE s.pid = '{IDS['A_V2']}'") == "1"


@pytest.mark.db
def test_i8_4_a_project_made_after_start_is_migrated_on_first_open(iso_client, iso_bed, auth):
    """The first open of a database the start did not see migrates it."""
    iso_client.get("/api/block-types")
    db = new_project(iso_bed, "9b000000-0000-4000-8000-000000000001", "first-open")
    r = iso_client.get("/api/p/first-open/layouts", headers=auth("alice"))
    assert r.status_code == 200 and r.json() == [], r.text[:300]
    assert iso_bed.scalar(db, "SELECT string_agg(name, ',' ORDER BY name) FROM report_composer.schema_migration") \
        == ("0001_project_database.sql,0002_layouts_without_data.sql,0003_numbering_on.sql,"
            "0004_layout_revisions.sql,0005_layouts_soft_deleted.sql,0006_pdf_copy.sql,0007_builtin_reports.sql")


@pytest.mark.db
def test_i8_4_the_first_open_waits_for_the_lock_of_that_database(iso_client, iso_bed, auth):
    """The migration of a project database takes lock 8_190_233_707 in THAT database."""
    import psycopg

    iso_client.get("/api/block-types")
    db = new_project(iso_bed, "9c000000-0000-4000-8000-000000000001", "locked-open")
    holder = psycopg.connect(iso_bed.su_dsn(db), autocommit=True)
    holder.execute("SELECT pg_advisory_lock(%s)", (LOCK,))
    result = {}

    def call():
        result["r"] = iso_client.get("/api/p/locked-open/layouts", headers=auth("alice"))

    th = threading.Thread(target=call)
    try:
        th.start()
        time.sleep(2.5)
        assert th.is_alive(), "the first open did not wait for the database's migration lock"
    finally:
        holder.execute("SELECT pg_advisory_unlock(%s)", (LOCK,))
        holder.close()
        th.join(30)
    assert result["r"].status_code == 200, result["r"].text[:300]


@pytest.mark.db
def test_i8_4_concurrent_first_opens_migrate_once(iso_client, iso_bed, auth):
    """Two first requests at once: both answer, the history has each file once."""
    iso_client.get("/api/block-types")
    db = new_project(iso_bed, "9d000000-0000-4000-8000-000000000001", "twice-open")
    results = []
    threads = [threading.Thread(target=lambda: results.append(
        iso_client.get("/api/p/twice-open/layouts", headers=auth("alice")).status_code)) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(60)
    assert results == [200, 200]
    files = len(list((Path(__file__).resolve().parents[1] / "migrations" / "project").glob("*.sql")))
    assert iso_bed.scalar(db, "SELECT count(*) FROM report_composer.schema_migration") == str(files)   # each file once


@pytest.mark.db
def test_i17_1_one_connection_per_call_closed_after(iso_client, iso_bed, auth, spy):
    """One connection per call, closed after: after a request no connection of the composer is left
    open, and no report_composer_rw session stays on the project database."""
    iso_client.get("/api/p/alpha/layouts", headers=auth("alice"))
    spy["reset"]()
    assert iso_client.get("/api/p/alpha/layouts", headers=auth("alice")).status_code == 200
    assert any(db == pdb(A) for db, _ in spy["connections"]), "the project database was not used"
    assert all(s.closed for _, s in spy["connections"]), "a connection outlived its call"
    assert iso_bed.scalar(pdb(A), "SELECT count(*) FROM pg_stat_activity WHERE usename = 'report_composer_rw'"
                                  f" AND datname = '{pdb(A)}'") == "0"


@pytest.mark.db
def test_i2_5_a_dropped_project_database_is_404_not_500(iso_client, iso_bed, auth):
    """The platform drops the database before it deletes the core.project row; in between the composer
    answers 404 for that project (never 500), also on the next call."""
    iso_client.get("/api/block-types")
    db = new_project(iso_bed, "9e000000-0000-4000-8000-000000000001", "to-be-dropped")
    lay = new_layout(iso_client, auth, slug="to-be-dropped", who="alice")
    iso_bed.psql("postgres", f'DROP DATABASE "{db}" WITH (FORCE)')
    for path in ("/api/p/to-be-dropped/layouts", f"/api/p/to-be-dropped/layouts/{lay['id']}",
                 "/api/p/to-be-dropped/layouts"):
        r = iso_client.get(path, headers=auth("alice"))
        assert r.status_code == 404, (path, r.status_code, r.text[:300])


