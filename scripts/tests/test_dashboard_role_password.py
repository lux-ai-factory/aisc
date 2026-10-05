"""dashboard_ro's password is generated, not its own name (as control_objectives_rw's).

dashboard_ro may connect to every project database and read its results, and reads every project's
members on `platform`. With the password `dashboard_ro`, any container on the backend network, plugin
code in the eval worker included, could read every project's results (security review 2026-10-05).
scripts/secrets.sh makes DASHBOARD_RO_PASSWORD, postgres-setup applies it (init/dashboard-role.sql), and
the dashboard gets it for its memberships DSN and the project connections its bridge registers."""
import re

import yaml

from conftest import ROOT

INFRA = yaml.safe_load((ROOT / "docker-compose-infra.development.yml").read_text())["services"]
APP = yaml.safe_load((ROOT / "docker-compose.development.yml").read_text())["services"]
REQUIRED = "${DASHBOARD_RO_PASSWORD:?run scripts/secrets.sh first}"


def test_secrets_sh_makes_the_password():
    assert re.search(r"^DASHBOARD_RO_PASSWORD=rand$", (ROOT / "scripts/secrets.sh").read_text(), re.M)


def test_postgres_setup_applies_it_on_every_start():
    setup = INFRA["postgres-setup"]
    assert setup["environment"]["DASHBOARD_RO_PASSWORD"] == REQUIRED
    assert "./init/dashboard-role.sql:/setup/dashboard-role.sql:ro,Z" in setup["volumes"]
    assert 'dashboard_ro_password=\\"$$DASHBOARD_RO_PASSWORD\\" -f /setup/dashboard-role.sql' in setup["command"]


def test_the_role_script_sets_it_and_keeps_the_default_only_without_one():
    text = (ROOT / "init/dashboard-role.sql").read_text()
    assert "\\if :{?dashboard_ro_password}" in text
    assert re.search(r"ALTER ROLE dashboard_ro .*PASSWORD %L", text)


def test_the_dashboard_logs_in_with_it():
    env = APP["dashboard"]["environment"]
    assert env["DASHBOARD_RO_PASSWORD"] == REQUIRED
    assert "dashboard_ro:dashboard_ro@" not in env["AISC_MEMBERSHIP_DB_URI"]
    assert REQUIRED in env["AISC_MEMBERSHIP_DB_URI"]


def test_the_access_check_script_reads_it_instead_of_the_default():
    assert "DASHBOARD_RO_PASSWORD" in (ROOT / "scripts/verify-db-access.sh").read_text()


def test_the_dashboard_signs_guest_tokens_with_a_generated_secret():
    """Embedding is on and guest tokens were signed with Superset's published default (2026-10-05)."""
    assert re.search(r"^SUPERSET_GUEST_TOKEN_SECRET=rand$", (ROOT / "scripts/secrets.sh").read_text(), re.M)
    assert APP["dashboard"]["environment"]["SUPERSET_GUEST_TOKEN_SECRET"] == \
        "${SUPERSET_GUEST_TOKEN_SECRET:?run scripts/secrets.sh first}"
