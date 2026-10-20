"""Every module's database role has a generated password, not its own name.

These roles connect to every project database or to `platform` and read or write what the module owns.
With the role's name as password, any container on the backend network, plugin code in the eval worker
included, could log in as any of them. scripts/secrets.sh makes each password, postgres-setup applies it
on every start (init/<module>-role.sql), and each service gets its URL or password from compose (which
overrides the module's env file). That the access check logs in with each one is
test_verify_db_access_passwords.py. Reads the files only; nothing is started."""
import re

import pytest
import yaml

from conftest import ROOT, aisc_py

INFRA = yaml.safe_load((ROOT / "docker-compose-infra.development.yml").read_text())["services"]
APP = yaml.safe_load((ROOT / "docker-compose.development.yml").read_text())["services"]

ROLES = [
    # role, env var, role script, (service, variable) pairs that log in as it
    ("platform_rw", "PLATFORM_RW_PASSWORD", "platform-role.sql", [("platform", "PLATFORM_DATABASE_URL")]),
    ("qualification_rw", "QUALIFICATION_RW_PASSWORD", "qualification-role.sql",
     [("qualification-web", "PROJECT_DATABASE_URL"), ("qualification-migrate", "PROJECT_DATABASE_URL")]),
    ("control_objectives_rw", "CONTROL_OBJECTIVES_RW_PASSWORD", "control-objectives-role.sql",
     [(name, var) for name in ("control-objectives", "control-objectives-migrate")
      for var in ("DATABASE_URL", "PROJECT_DATABASE_URL")]),
    ("controls_rw", "CONTROLS_RW_PASSWORD", "controls-role.sql",
     [("controls-web", "PROJECT_DATABASE_URL"), ("controls-migrate", "PROJECT_DATABASE_URL")]),
    # no service of this stack logs in as catalogue_rw (catalogue-private is the frontend only; the
    # catalogue backend is the hosted one), but the role can log in, so it gets a password all the same
    ("catalogue_rw", "CATALOGUE_RW_PASSWORD", "catalogue-role.sql", []),
    # the dashboard gets the password itself too, for the project connections its bridge registers
    ("dashboard_ro", "DASHBOARD_RO_PASSWORD", "dashboard-role.sql",
     [("dashboard", "AISC_MEMBERSHIP_DB_URI"), ("dashboard", "DASHBOARD_RO_PASSWORD")]),
    # the engine's logins (DB_PASSWORD, from x-backend-env) are test_engine_rw_and_run_ticket.py
    ("engine_rw", "ENGINE_RW_PASSWORD", "engine-role.sql", []),
]


def required(var):
    return "${%s:?run scripts/secrets.sh first}" % var


@pytest.mark.parametrize("role, var, script, logins", ROLES)
def test_secrets_sh_makes_the_password(role, var, script, logins):
    assert dict(aisc_py().SECRETS)[var] == "rand"


@pytest.mark.parametrize("role, var, script, logins", ROLES)
def test_postgres_setup_applies_it_on_every_start(role, var, script, logins):
    setup = INFRA["postgres-setup"]
    assert setup["environment"][var] == required(var)
    assert f"./init/{script}:/setup/{script}:ro,Z" in setup["volumes"]
    assert f'{role}_password=\\"$${var}\\" -f /setup/{script}' in setup["command"]


@pytest.mark.parametrize("role, var, script, logins", ROLES)
def test_the_role_script_sets_it_and_keeps_the_default_only_without_one(role, var, script, logins):
    text = (ROOT / "init" / script).read_text()
    assert f"\\if :{{?{role}_password}}" in text
    assert re.search(rf"ALTER ROLE {role} .*PASSWORD %L", text)


@pytest.mark.parametrize("role, var, script, logins", ROLES)
def test_each_service_logs_in_with_it(role, var, script, logins):
    for name, url in logins:
        value = (APP[name].get("environment") or {}).get(url, "")
        # a URL carries the role and the required password; a bare password variable is the required one
        assert value == required(var) or f"{role}:{required(var)}@postgres:5432/" in value, f"{name} {url}: {value!r}"
        assert f"{role}:{role}@" not in value


def test_the_dashboard_signs_guest_tokens_with_a_generated_secret():
    """Embedding is on, so guest tokens must not be signed with Superset's published default: the secret
    is generated."""
    assert dict(aisc_py().SECRETS)["SUPERSET_GUEST_TOKEN_SECRET"] == "rand"
    assert APP["dashboard"]["environment"]["SUPERSET_GUEST_TOKEN_SECRET"] == \
        "${SUPERSET_GUEST_TOKEN_SECRET:?run scripts/secrets.sh first}"
