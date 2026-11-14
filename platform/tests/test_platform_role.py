"""platform_rw may not end other roles' sessions: deleting a project ends the apps' sessions on its database
through aisc_setup.end_project_sessions, which only platform_owner may call (init/owner-roles.sql, run by
postgres-setup on every start, which also takes back the pg_signal_backend that older versions of
init/platform-role.sql granted)."""
import os
import re
from pathlib import Path

import psycopg
import pytest

INIT = Path(__file__).resolve().parents[2] / "init"
ROLE_SQL = INIT / "platform-role.sql"
OWNER_SQL = INIT / "owner-roles.sql"


def test_the_role_files_take_pg_signal_backend_back_on_every_start():
    assert not re.search(r"^GRANT pg_signal_backend", ROLE_SQL.read_text(), re.M)
    text = OWNER_SQL.read_text()
    assert re.search(r"^REVOKE pg_signal_backend FROM platform_rw;", text, re.M)
    conditional = "".join(text[a:b] for a, b in
                          ((m.start(), text.index("\\endif", m.start())) for m in re.finditer(r"\\if", text)))
    assert "pg_signal_backend" not in conditional, "the revoke must not depend on a password being passed"


@pytest.mark.skipif(not os.environ.get("PLATFORM_TEST_SUPERUSER_URL"), reason="no throwaway superuser URL")
def test_on_a_set_up_database_platform_rw_is_not_a_member_and_the_function_exists():
    with psycopg.connect(os.environ["PLATFORM_TEST_SUPERUSER_URL"]) as conn:
        assert not conn.execute("SELECT pg_has_role('platform_rw', 'pg_signal_backend', 'MEMBER')").fetchone()[0]
        assert conn.execute("SELECT to_regprocedure('aisc_setup.end_project_sessions(text)') IS NOT NULL"
                            ).fetchone()[0]
