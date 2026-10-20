"""platform_rw may end the apps' sessions on a project database it is deleting (init/platform-role.sql,
run by postgres-setup on every start). DROP DATABASE ... WITH (FORCE) needs it; without it a project an
app has opened can't be deleted."""
import os
import re
from pathlib import Path

import psycopg
import pytest

ROLE_SQL = Path(__file__).resolve().parents[2] / "init/platform-role.sql"


def test_the_role_file_grants_pg_signal_backend_on_every_start():
    text = ROLE_SQL.read_text()
    grant = re.search(r"^GRANT pg_signal_backend TO platform_rw;", text, re.M)
    assert grant, "init/platform-role.sql must grant pg_signal_backend to platform_rw"
    conditional = text[text.index("\\if"):text.index("\\endif")]
    assert "pg_signal_backend" not in conditional, "the grant must not depend on a password being passed"


@pytest.mark.skipif(not os.environ.get("PLATFORM_TEST_SUPERUSER_URL"), reason="no throwaway superuser URL")
def test_on_a_set_up_database_platform_rw_is_a_member():
    with psycopg.connect(os.environ["PLATFORM_TEST_SUPERUSER_URL"]) as conn:
        assert conn.execute("SELECT pg_has_role('platform_rw', 'pg_signal_backend', 'MEMBER')").fetchone()[0]
