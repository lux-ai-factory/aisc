"""init/chart-assistant-role.sql: the chart assistant's role makes and reads its mock databases and nothing else.
The platform database is open to PUBLIC by default (CONNECT and TEMPORARY), so revoking from the role alone left
it free to connect there and read the catalog; the roles that work in platform hold CONNECT of their own."""
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
from pipeline_chain.throwaway import Throwaway  # noqa: E402


@pytest.fixture(scope="module")
def pg():
    t = Throwaway.start("chartrole")
    yield t
    t.stop()


def _privilege(pg, role, privilege):
    return pg.scalar("platform", f"SELECT has_database_privilege('{role}', 'platform', '{privilege}')")


def test_the_chart_assistant_cannot_connect_to_the_platform_database(pg):
    pg.psql("platform", "CREATE ROLE platform_rw LOGIN; GRANT CONNECT ON DATABASE platform TO platform_rw;")
    for _ in range(2):  # every start runs it again
        r = pg.psql("platform", "\\set assistant_mock_password 'pw'\n"
                    + (ROOT / "init/chart-assistant-role.sql").read_text(), check=False)
        assert r.returncode == 0, r.stderr
    assert _privilege(pg, "assistant_mock", "CONNECT") == "f"
    assert _privilege(pg, "assistant_mock", "TEMPORARY") == "f"
    assert _privilege(pg, "platform_rw", "CONNECT") == "t"
