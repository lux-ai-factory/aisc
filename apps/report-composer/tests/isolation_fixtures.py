"""Test infrastructure for the composer on one database per project.

The bed is `scripts/lib/report_bed_isolated.build_isolated(modules=False)`:
the composer bed's core seed (alpha, beta, gamma, echo, their versions and members), then the isolated shape:
alpha, beta and echo each have `project_<hex>` with `project.system` (their own versions) and an empty
`report_composer` schema; gamma has no database; `platform` keeps core.project and core.project_member only,
has no report_composer schema and no core.system, and has an empty `report_library` schema (owner
report_composer_rw). Alice is made an editor of beta as well, so a 404 across projects is the database's
answer, not the membership's.

The API the tests assume of `report_composer`:

    report_composer.app.create_app(*, database_url, project_database_url, renderer, clock=None) -> FastAPI
        database_url          REPORT_COMPOSER_DATABASE_URL, `platform` as report_composer_rw: core.project,
                              core.project_member and report_library only
        project_database_url  REPORT_COMPOSER_PROJECT_DATABASE_URL, the same DSN with `{database}` in place of
                              the name; everything of a project (report_composer.*, project.system)
    migrations/project/0001_project_database.sql, tracked in report_composer.schema_migration of each project
    migrations/library/0001_presets.sql, tracked in report_library.schema_migration of `platform`

Never the host's 5432.
"""
from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

import pytest

from conftest import ISSUER, ORIGIN, FIXED_NOW, lazily, need

ROOT = Path(__file__).resolve().parents[3]           # the aisc repository root
sys.path.insert(0, str(ROOT / "scripts/lib"))
import report_bed  # noqa: E402

IDS = report_bed.IDS
LOCK = 8_190_233_707
MODULE_TABLES = ("layout", "layout_block", "template", "generated_report")


def pdb(pid: str) -> str:
    return report_bed.project_db(pid)


def _iso():
    try:
        return importlib.import_module("report_bed_isolated")
    except ModuleNotFoundError:
        pytest.fail("scripts/lib/report_bed_isolated.py is missing from the worktree", pytrace=False)


@pytest.fixture(scope="session")
def iso_bed():
    iso = _iso()
    report_bed.check_dsn_env()
    b = iso.build_isolated("iso-R-composer", modules=False)
    try:
        b.psql("platform", "INSERT INTO core.project_member (project_id, subject, email, role)"
                           f" VALUES ('{IDS['B']}', 'alice', 'alice@localhost', 'editor')")
        yield b
    finally:
        b.stop()


def new_project(bed, pid: str, slug: str, owner: str = "alice") -> str:
    """A project made after the composer started: core.project row, owner, and its database as the platform
    makes it (from the project templates)."""
    iso = _iso()
    bed.psql("platform", f"INSERT INTO core.project (pid, name, slug) VALUES ('{pid}', '{slug} project', '{slug}')")
    bed.psql("platform", "INSERT INTO core.project_member (project_id, subject, email, role)"
                         f" VALUES ('{pid}', '{owner}', '{owner}@localhost', 'owner')")
    name = report_bed._project_database(bed.t, pid)
    number_one = "1" + pid[1:]
    stand_in = "" if not iso.missing_templates() else f"""
        CREATE SCHEMA IF NOT EXISTS project AUTHORIZATION platform_rw;
        CREATE TABLE IF NOT EXISTS project.system (pid uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          number integer NOT NULL UNIQUE CHECK (number > 0), name text NOT NULL, version text, provider text,
          description text, created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(), created_by text);
        ALTER TABLE project.system OWNER TO platform_rw;
        GRANT USAGE ON SCHEMA project TO report_composer_rw;
        GRANT SELECT, REFERENCES ON project.system TO report_composer_rw;
        CREATE SCHEMA IF NOT EXISTS report_composer AUTHORIZATION platform_rw;
        GRANT CONNECT ON DATABASE "{name}" TO report_composer_rw;
        GRANT USAGE, CREATE ON SCHEMA report_composer TO report_composer_rw;
        ALTER ROLE report_composer_rw IN DATABASE "{name}" SET search_path = report_composer;
    """
    bed.psql(name, stand_in + f"INSERT INTO project.system (pid, number, name) VALUES ('{number_one}', 1, '{slug}');")
    return name


def project_db_template(bed) -> str:
    return f"postgresql://report_composer_rw:report_composer_rw@127.0.0.1:{bed.port}/{{database}}"


@pytest.fixture
def iso_make_client(iso_bed, key, monkeypatch):
    """The composer app on the bed with both DSNs and authentication on, like the conftest's make_client."""
    platform = iso_bed.dsn("report_composer_rw", "platform")
    template = project_db_template(iso_bed)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("KEYCLOAK_ISSUER", ISSUER)
    monkeypatch.setenv("KEYCLOAK_JWKS_URL", "http://keycloak:8080/unused-in-tests")
    monkeypatch.setenv("PLATFORM_ORIGIN", ORIGIN)
    monkeypatch.setenv("REPORT_COMPOSER_DATABASE_URL", platform)
    monkeypatch.setenv("REPORT_COMPOSER_PROJECT_DATABASE_URL", template)
    monkeypatch.setenv("REPORT_SERVICE_TOKEN", "composer-test-token-0123456789")
    import aisc_identity.service

    monkeypatch.setattr(aisc_identity.service, "key_for_jwks", lambda url: (lambda _t: key.public_key()))
    opened = []

    def make(renderer, clock=lambda: FIXED_NOW):
        from fastapi.testclient import TestClient

        def build():
            create_app = need("report_composer.app", "create_app")
            try:
                app = create_app(database_url=platform, project_database_url=template, renderer=renderer, clock=clock)
            except TypeError as exc:
                if "project_database_url" in str(exc):
                    pytest.fail("missing feature: create_app(project_database_url=...) (I8.1)", pytrace=False)
                raise
            c = TestClient(app, base_url="http://localhost")
            c.__enter__()
            opened.append(c)
            return c

        return lazily(build)

    yield make
    for c in opened:
        c.__exit__(None, None, None)


@pytest.fixture
def iso_clean(iso_bed):
    """Every test starts with no layouts, templates, reports or saved presets (the tables may not exist yet)."""
    for key in ("A", "B", "E"):
        iso_bed.psql(pdb(IDS[key]), "DO $$ BEGIN IF to_regclass('report_composer.layout') IS NOT NULL THEN "
                                    "TRUNCATE report_composer.layout, report_composer.template CASCADE; END IF; END $$;",
                     check=False)
    iso_bed.psql("platform", "DO $$ BEGIN IF to_regclass('report_library.preset') IS NOT NULL THEN "
                             "DELETE FROM report_library.preset; END IF; END $$;", check=False)
    yield


class _Spy:
    """A psycopg connection that records every execute as (database, sql); a context manager like the real one."""

    def __init__(self, conn, log):
        self._conn, self._log = conn, log
        self.database = conn.info.dbname

    def execute(self, sql, *a, **k):
        self._log["sql"].append((self.database, str(sql)))
        return self._conn.execute(sql, *a, **k)

    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, *exc):
        return self._conn.__exit__(*exc)

    def __getattr__(self, name):
        return getattr(self._conn, name)


@pytest.fixture
def spy(monkeypatch):
    """Every connection the composer opens from now on: log["connections"] (database, spy), log["sql"]."""
    import psycopg

    log = {"connections": [], "sql": []}
    real = psycopg.connect

    def connect(*a, **k):
        s = _Spy(real(*a, **k), log)
        log["connections"].append((s.database, s))
        return s

    monkeypatch.setattr(psycopg, "connect", connect)
    log["reset"] = lambda: (log["connections"].clear(), log["sql"].clear())
    return log


def tables_named(sql: str) -> set[str]:
    import re

    return {t.lower() for t in re.findall(r"\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+([A-Za-z_]+\.[A-Za-z_]+)", sql, re.I)}


def unique(prefix: str) -> str:
    return f"{prefix} {time.monotonic_ns()}"
