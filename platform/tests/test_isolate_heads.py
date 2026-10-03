"""The engine migration names the isolate tool checks.

No database: these run in every platform suite, while tests/test_isolate.py skips without a
throwaway cluster. The source of an isolate run is an old install, at the OLD chain's head
(0024_no_login_of_its_own): that name stays. A target is a project database made by the current
engine, whose chain is the engine's 0001..0014 and this branch's 0015..0021.
"""
from pathlib import Path

import isolate_support as S
from platform_service.isolate import preconditions as P

MIGRATIONS = Path(__file__).resolve().parents[2] / "apps/backend/aisc_backend/migrations"


def engine_chain() -> list[str]:
    return sorted(p.stem for p in MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.py"))


def test_the_new_head_is_a_migration_of_todays_engine():
    chain = engine_chain()
    assert chain, f"no migrations in {MIGRATIONS}"
    assert P.NEW_DJANGO in chain, (P.NEW_DJANGO, chain[-4:])
    # the head is the LAST migration: a target that stopped before it is not at the new head
    assert P.NEW_DJANGO == chain[-1] == "0021_engine_deployment_marker", (P.NEW_DJANGO, chain[-4:])
    assert S.NEW_DJANGO == P.NEW_DJANGO


def test_a_target_records_the_chain_todays_engine_makes():
    assert S.NEW_DJANGO_CHAIN == engine_chain()


def test_the_old_head_names_the_old_chain_on_purpose():
    assert P.OLD_DJANGO_HEAD == S.OLD_DJANGO[-1] == "0024_no_login_of_its_own"
    assert P.OLD_DJANGO_HEAD not in engine_chain()
