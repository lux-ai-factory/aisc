"""platform_rw's password is generated, not its own name (phase 2 review M1).

The platform service is the only writer of the ledger's Postgres side (witness records, pool, state)
and of ledger_identity, the database that names people (S8). With the password `platform_rw`, any
container on the backend network, the eval worker running plugin code included, could log in as it.
Now scripts/secrets.sh makes PLATFORM_RW_PASSWORD, postgres-setup applies it on every start
(init/platform-role.sql, like init/report-roles.sql), and the platform's URL is built from it. Reads
the files only; nothing is started.
"""
import re

import yaml

from conftest import ROOT

INFRA = yaml.safe_load((ROOT / "docker-compose-infra.development.yml").read_text())["services"]
APP = yaml.safe_load((ROOT / "docker-compose.development.yml").read_text())["services"]


def test_secrets_sh_makes_the_password():
    assert re.search(r"^PLATFORM_RW_PASSWORD=rand$", (ROOT / "scripts/secrets.sh").read_text(), re.M)


def test_postgres_setup_applies_it_on_every_start():
    setup = INFRA["postgres-setup"]
    assert setup["environment"]["PLATFORM_RW_PASSWORD"] == "${PLATFORM_RW_PASSWORD:?run scripts/secrets.sh first}"
    assert "./init/platform-role.sql:/setup/platform-role.sql:ro,Z" in setup["volumes"]
    assert 'platform_rw_password=\\"$$PLATFORM_RW_PASSWORD\\" -f /setup/platform-role.sql' in setup["command"]


def test_the_role_script_sets_it_and_keeps_the_default_only_without_one():
    text = (ROOT / "init/platform-role.sql").read_text()
    assert "\\if :{?platform_rw_password}" in text
    assert re.search(r"ALTER ROLE platform_rw .*PASSWORD %L", text)


def test_the_platform_logs_in_with_it():
    url = APP["platform"]["environment"]["PLATFORM_DATABASE_URL"]
    assert "platform_rw:platform_rw@" not in url
    assert "${PLATFORM_RW_PASSWORD:?run scripts/secrets.sh first}" in url


def test_the_access_check_script_reads_it_instead_of_the_default():
    text = (ROOT / "scripts/verify-db-access.sh").read_text()
    assert "platform_rw:platform_rw@" not in text and "PLATFORM_RW_PASSWORD" in text
