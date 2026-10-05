"""qualification_rw's password is generated, not its own name (as platform_rw's, test_platform_role_password.py).

qualification_rw may connect to every project database and write its qualification schema. With the
password `qualification_rw`, any container on the backend network, the eval worker running plugin code
included, could log in as it and read or change every project's cards (security review 2026-10-05). So
scripts/secrets.sh makes QUALIFICATION_RW_PASSWORD, postgres-setup applies it on every start
(init/qualification-role.sql), and qualification's URL is built from it. Reads the files only.
"""
import re

import yaml

from conftest import ROOT

INFRA = yaml.safe_load((ROOT / "docker-compose-infra.development.yml").read_text())["services"]
APP = yaml.safe_load((ROOT / "docker-compose.development.yml").read_text())["services"]


def test_secrets_sh_makes_the_password():
    assert re.search(r"^QUALIFICATION_RW_PASSWORD=rand$", (ROOT / "scripts/secrets.sh").read_text(), re.M)


def test_postgres_setup_applies_it_on_every_start():
    setup = INFRA["postgres-setup"]
    assert setup["environment"]["QUALIFICATION_RW_PASSWORD"] == \
        "${QUALIFICATION_RW_PASSWORD:?run scripts/secrets.sh first}"
    assert "./init/qualification-role.sql:/setup/qualification-role.sql:ro,Z" in setup["volumes"]
    assert 'qualification_rw_password=\\"$$QUALIFICATION_RW_PASSWORD\\" -f /setup/qualification-role.sql' \
        in setup["command"]


def test_the_role_script_sets_it_and_keeps_the_default_only_without_one():
    text = (ROOT / "init/qualification-role.sql").read_text()
    assert "\\if :{?qualification_rw_password}" in text
    assert re.search(r"ALTER ROLE qualification_rw .*PASSWORD %L", text)


def test_every_qualification_service_logs_in_with_it():
    for name in ("qualification-web", "qualification-migrate"):
        url = APP[name]["environment"]["PROJECT_DATABASE_URL"]
        assert "qualification_rw:qualification_rw@" not in url, name
        assert "${QUALIFICATION_RW_PASSWORD:?run scripts/secrets.sh first}" in url, name


def test_the_access_check_script_reads_it_instead_of_the_default():
    text = (ROOT / "scripts/verify-db-access.sh").read_text()
    assert "QUALIFICATION_RW_PASSWORD" in text
