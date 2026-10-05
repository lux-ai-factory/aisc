"""control_objectives_rw's password is generated, not its own name (as qualification_rw's).

control_objectives_rw may connect to every project database and write its control_objectives schema,
read every project's members, and post ledger events. With the
password `control_objectives_rw`, any container on the backend network, the eval worker running plugin code
included, could log in as it and read or change every project's risk register (security review 2026-10-05). So
scripts/secrets.sh makes CONTROL_OBJECTIVES_RW_PASSWORD, postgres-setup applies it on every start
(init/control-objectives-role.sql), and control objectives' URLs are built from it. Reads the files only.
"""
import re

import yaml

from conftest import ROOT

INFRA = yaml.safe_load((ROOT / "docker-compose-infra.development.yml").read_text())["services"]
APP = yaml.safe_load((ROOT / "docker-compose.development.yml").read_text())["services"]


def test_secrets_sh_makes_the_password():
    assert re.search(r"^CONTROL_OBJECTIVES_RW_PASSWORD=rand$", (ROOT / "scripts/secrets.sh").read_text(), re.M)


def test_postgres_setup_applies_it_on_every_start():
    setup = INFRA["postgres-setup"]
    assert setup["environment"]["CONTROL_OBJECTIVES_RW_PASSWORD"] == \
        "${CONTROL_OBJECTIVES_RW_PASSWORD:?run scripts/secrets.sh first}"
    assert "./init/control-objectives-role.sql:/setup/control-objectives-role.sql:ro,Z" in setup["volumes"]
    assert 'control_objectives_rw_password=\\"$$CONTROL_OBJECTIVES_RW_PASSWORD\\" -f /setup/control-objectives-role.sql' \
        in setup["command"]


def test_the_role_script_sets_it_and_keeps_the_default_only_without_one():
    text = (ROOT / "init/control-objectives-role.sql").read_text()
    assert "\\if :{?control_objectives_rw_password}" in text
    assert re.search(r"ALTER ROLE control_objectives_rw .*PASSWORD %L", text)


def test_every_control_objectives_service_logs_in_with_it():
    for name in ("control-objectives", "control-objectives-migrate"):
        for var in ("DATABASE_URL", "PROJECT_DATABASE_URL"):
            url = APP[name]["environment"][var]
            assert "control_objectives_rw:control_objectives_rw@" not in url, (name, var)
            assert "${CONTROL_OBJECTIVES_RW_PASSWORD:?run scripts/secrets.sh first}" in url, (name, var)


def test_the_access_check_script_reads_it_instead_of_the_default():
    text = (ROOT / "scripts/verify-db-access.sh").read_text()
    assert "CONTROL_OBJECTIVES_RW_PASSWORD" in text
