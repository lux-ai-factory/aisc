"""Daily backups of every database, each restored into a throwaway and counted.

scripts/backup-databases.sh dumps platform, keycloak, superset and every project database from one snapshot
per database (the counts and the dump agree), writes the files private (0600) outside the checkout, keeps
the newest N per database, restores the newest of each into a throwaway Postgres and compares the row counts
table by table.

The stack's Postgres is never used: BACKUP_PG_CONTAINER points the script at a throwaway one (backup_bed.py).

    cd scripts/tests && uv run --no-project --with pytest --with pyyaml --with 'psycopg[binary]' pytest -q -p no:cacheprovider test_backup_databases.py
"""
from __future__ import annotations

import subprocess

import pytest

import backup_bed
from conftest import ROOT

SCRIPT = ROOT / "scripts/backup-databases.sh"
ONE = ROOT / "scripts/lib/backup-one.sql"


def run(args, env=None):
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=ROOT, capture_output=True, text=True, env=env,
                          timeout=600)


@pytest.fixture(scope="module")
def bed(tmp_path_factory):
    made = backup_bed.start(tmp_path_factory.mktemp("backup-bed"))
    yield made
    backup_bed.stop(made)


def test_the_backup_script_exists():
    assert SCRIPT.is_file(), "scripts/backup-databases.sh does not exist"


def test_every_database_is_dumped_private_and_restored_with_equal_counts(tmp_path, bed):
    r = run(["--dir", str(tmp_path)], env=bed.env)
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    dumps = sorted(p.name.split("_2")[0] for p in tmp_path.glob("*.dump"))
    assert dumps == sorted(backup_bed.DATABASES)
    modes = {oct(p.stat().st_mode & 0o777) for p in tmp_path.iterdir() if p.is_file()}
    assert modes == {"0o600"}, modes
    for db in backup_bed.DATABASES:
        assert f"restore-check {db} PASS" in r.stdout, f"no passing restore check for {db}"
    assert "FAIL" not in r.stdout


def test_the_counts_and_the_dump_come_from_one_snapshot():
    assert ONE.is_file(), "scripts/lib/backup-one.sql does not exist"
    sql = ONE.read_text()
    assert "pg_export_snapshot()" in sql and "--snapshot=" in sql and "REPEATABLE READ" in sql


def test_a_backup_folder_inside_the_checkout_is_refused():
    r = run(["--dir", str(ROOT / "backups")])
    assert r.returncode == 2, (r.stdout + r.stderr)[-1000:]
    assert "outside the checkout" in r.stderr
    assert not (ROOT / "backups").exists()


def test_old_dumps_beyond_keep_are_removed(tmp_path, bed):
    for _ in range(3):
        r = run(["--dir", str(tmp_path), "--keep", "2", "--no-restore-check"], env=bed.env)
        assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    assert len(list(tmp_path.glob("platform_*.dump"))) == 2


def test_a_restore_that_differs_fails_and_names_the_table(tmp_path, bed):
    r = run(["--dir", str(tmp_path), "--no-restore-check"], env=bed.env)
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    counts = sorted(tmp_path.glob("platform_*.counts"))
    assert counts, "no counts file was written beside the dump"
    text = counts[-1].read_text()
    assert "core.project" in text, "the counts file does not list core.project"
    counts[-1].write_text(text.replace("core.project\t7", "core.project\t8").replace("core.project 7",
                                                                                      "core.project 8"))
    r = run(["--dir", str(tmp_path), "--restore-check-only"], env=bed.env)
    assert r.returncode == 1, (r.stdout + r.stderr)[-2000:]
    assert "FAIL: core.project" in r.stdout
