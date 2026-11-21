"""ledger-pool gives a project that has no ledger database yet (made while the pool was empty) one of the pool's.
That goes through the platform's own database pool, whose first use migrates core as platform_migrator: without
PLATFORM_MIGRATE_DATABASE_URL the one-shot fails, and every service waiting for it never starts."""
import yaml

from conftest import ROOT


def _environment(service: str) -> dict:
    compose = yaml.safe_load((ROOT / "docker-compose.development.yml").read_text())
    return compose["services"][service]["environment"]


def test_ledger_pool_can_migrate_the_platform_database_as_the_platform_does():
    pool = _environment("ledger-pool")
    assert "PLATFORM_MIGRATE_DATABASE_URL" in pool
    assert pool["PLATFORM_MIGRATE_DATABASE_URL"] == _environment("platform")["PLATFORM_MIGRATE_DATABASE_URL"]
