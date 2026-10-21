"""init/keycloak-role.sql and init/superset-role.sql: Keycloak and Superset connect with roles of their
own, not the Postgres superuser. Checked on a volume made before the files: what the
superuser created there is handed over, grants others hold stay, and every start can run them again."""

import subprocess
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
from pipeline_chain.throwaway import Throwaway  # noqa: E402

CASES = [("keycloak", "keycloak_app", "keycloak-role.sql"), ("superset", "superset_app", "superset-role.sql")]


@pytest.fixture(scope="module")
def pg():
    t = Throwaway.start("approles")
    yield t
    t.stop()


def _run(pg, script, password="pw"):
    """As postgres-setup runs it: the superuser, the password as a psql variable."""
    return pg.psql("platform", f"\\set app_password '{password}'\n" + (ROOT / "init" / script).read_text(),
                   check=False)


@pytest.mark.parametrize("db,role,script", CASES)
def test_an_old_volume_hands_its_objects_to_the_app_role(pg, db, role, script):
    pg.psql("platform", f"CREATE DATABASE {db};")
    pg.psql(db, "CREATE TABLE t(id serial); CREATE SEQUENCE s; CREATE VIEW v AS SELECT 1 AS x;"
                "CREATE TYPE mood AS ENUM ('a'); CREATE FUNCTION f() RETURNS int LANGUAGE sql AS 'SELECT 1';"
                "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'report_ro') THEN "
                "CREATE ROLE report_ro LOGIN; END IF; END $$; GRANT SELECT ON t TO report_ro;"
                f"REVOKE CONNECT ON DATABASE {db} FROM PUBLIC;")
    r = _run(pg, script)
    assert r.returncode == 0, r.stderr
    assert pg.scalar("platform", f"SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='{db}'") == role
    assert pg.scalar(db, "SELECT tableowner FROM pg_tables WHERE tablename='t'") == role
    assert pg.scalar(db, "SELECT sequenceowner FROM pg_sequences WHERE sequencename='s'") == role
    assert pg.scalar(db, "SELECT sequenceowner FROM pg_sequences WHERE sequencename='t_id_seq'") == role
    assert pg.scalar(db, "SELECT viewowner FROM pg_views WHERE viewname='v'") == role
    assert pg.scalar(db, "SELECT pg_get_userbyid(typowner) FROM pg_type WHERE typname='mood'") == role
    assert pg.scalar(db, "SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE proname='f'") == role
    assert pg.scalar("platform", f"SELECT rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles "
                                 f"WHERE rolname='{role}'") == "f"
    assert pg.scalar(db, "SELECT has_table_privilege('report_ro', 't', 'SELECT')") == "t"
    # it logs in with the password it was given, though PUBLIC may not connect
    login = subprocess.run(["docker", "exec", "-e", "PGPASSWORD=pw", pg.name, "psql", "-X", "-tA", "-h",
                            "127.0.0.1", "-U", role, "-d", db, "-c", "SELECT count(*) FROM t"],
                           capture_output=True, text=True)
    assert login.returncode == 0 and login.stdout.strip() == "0", login.stderr
    r = _run(pg, script)        # every start runs it again
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("db,role,script", CASES)
def test_a_volume_without_the_database_is_left_alone(db, role, script):
    """An install whose volume has no such database (its initdb script came later) still starts."""
    t = Throwaway.start("approles-none")
    try:
        r = _run(t, script)
        assert r.returncode == 0, r.stderr
        assert t.scalar("platform", f"SELECT count(*) FROM pg_database WHERE datname='{db}'") == "0"
    finally:
        t.stop()
