"""controls_rw's and catalogue_rw's passwords are generated, not their own names (review pass 2026-10-06,
as qualification_rw, control_objectives_rw and dashboard_ro before them).

controls_rw connects to every project database and writes its controls schema; catalogue_rw writes the
catalogue schema on `platform` (no service here uses it, the role can still log in). With the role's name as password, any container on the backend network,
plugin code in the eval worker included, could log in as either. scripts/secrets.sh makes the passwords,
postgres-setup applies them on every start (init/<module>-role.sql), and each service gets its URL with
the password from compose (which overrides the module's env file)."""
import re

import pytest
import yaml

from conftest import ROOT

INFRA = yaml.safe_load((ROOT / "docker-compose-infra.development.yml").read_text())["services"]
APP = yaml.safe_load((ROOT / "docker-compose.development.yml").read_text())["services"]

ROLES = [
    # role, env var, role script, services that log in as it, their URL variable
    ("controls_rw", "CONTROLS_RW_PASSWORD", "controls-role.sql", ["controls-web", "controls-migrate"],
     "PROJECT_DATABASE_URL"),
    # no service of this stack logs in as catalogue_rw (catalogue-private is the frontend only; the
    # catalogue backend is the hosted one), but the role can log in, so it gets a password all the same
    ("catalogue_rw", "CATALOGUE_RW_PASSWORD", "catalogue-role.sql", [], "DATABASE_URL"),
]


def required(var):
    return "${%s:?run scripts/secrets.sh first}" % var


@pytest.mark.parametrize("role, var, script, services, url", ROLES)
def test_secrets_sh_makes_the_password(role, var, script, services, url):
    assert re.search(rf"^{var}=rand$", (ROOT / "scripts/secrets.sh").read_text(), re.M)


@pytest.mark.parametrize("role, var, script, services, url", ROLES)
def test_postgres_setup_applies_it_on_every_start(role, var, script, services, url):
    setup = INFRA["postgres-setup"]
    assert setup["environment"][var] == required(var)
    assert f"./init/{script}:/setup/{script}:ro,Z" in setup["volumes"]
    assert f'{role}_password=\\"$${var}\\" -f /setup/{script}' in setup["command"]


@pytest.mark.parametrize("role, var, script, services, url", ROLES)
def test_the_role_script_sets_it_and_keeps_the_default_only_without_one(role, var, script, services, url):
    text = (ROOT / "init" / script).read_text()
    assert f"\\if :{{?{role}_password}}" in text
    assert re.search(rf"ALTER ROLE {role} .*PASSWORD %L", text)


@pytest.mark.parametrize("role, var, script, services, url", ROLES)
def test_each_service_logs_in_with_it(role, var, script, services, url):
    for name in services:
        value = (APP[name].get("environment") or {}).get(url, "")
        assert f"{role}:{required(var)}@postgres:5432/" in value, f"{name}: {value!r}"
        assert f"{role}:{role}@" not in value


@pytest.mark.parametrize("role, var, script, services, url", ROLES)
def test_the_access_check_script_reads_it_instead_of_the_default(role, var, script, services, url):
    text = (ROOT / "scripts/verify-db-access.sh").read_text()
    assert var in text and re.search(rf"{role}\) PW=\${{{var}:-{role}}}", text)
