"""`python -m report_composer.migrate` follows the migrate one-shots' exit convention (isolation, orchestrator's
decision for WP V1; the same as qualification's and controls' migrate-projects.mjs, control objectives'
migrate_projects and the engine's migrate_projects):

    0  the library and every project database are at their head
    1  the platform database cannot be reached yet: the compose loop waits and runs it again
    2  a permanent failure (a missing setting, the library or a project database that failed): the loop
       stops, and report-composer does not start on a half-migrated set

No database is touched: the functions that would connect are replaced.
"""
from __future__ import annotations

import psycopg
import pytest

from report_composer import migrate

ENV = {"REPORT_COMPOSER_DATABASE_URL": "postgresql://report_composer_rw@127.0.0.1:1/platform",
       "REPORT_COMPOSER_PROJECT_DATABASE_URL": "postgresql://report_composer_rw@127.0.0.1:1/{database}"}


@pytest.fixture
def env(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)


@pytest.mark.parametrize("missing", list(ENV))
def test_a_missing_setting_is_permanent(monkeypatch, env, missing):
    monkeypatch.delenv(missing)
    assert migrate.main([]) == 2


def test_an_unreachable_platform_is_retried(monkeypatch, env):
    def unreachable(url):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(migrate, "project_databases", unreachable)
    monkeypatch.setattr(migrate, "migrate_everything",
                        lambda *a, **k: pytest.fail("nothing is migrated before the platform answers"))
    assert migrate.main([]) == 1


@pytest.mark.parametrize("results", [
    {"report_library": "failed: SchemaMissing", "project_a": "ok"},
    {"report_library": "ok", "project_a": "ok", "project_b": "failed: UndefinedTable"},
])
def test_a_failed_database_is_permanent(monkeypatch, env, results):
    monkeypatch.setattr(migrate, "project_databases", lambda url: [])
    monkeypatch.setattr(migrate, "migrate_everything", lambda *a, **k: results)
    assert migrate.main([]) == 2


def test_everything_at_its_head_is_0(monkeypatch, env):
    monkeypatch.setattr(migrate, "project_databases", lambda url: [])
    monkeypatch.setattr(migrate, "migrate_everything", lambda *a, **k: {"report_library": "ok", "project_a": "ok"})
    assert migrate.main([]) == 0
