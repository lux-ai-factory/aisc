"""The engine's database role and its run tickets (review pass 2026-10-06).

engine_rw's password is generated, not its own name (as controls_rw's): the engine connects to every project
database. Its run tickets, which bind a plugin's calls back into the engine to its own project and evaluation,
are keyed with RUN_TICKET_KEY, which only the backend holds: the eval worker runs third-party plugin code and
must hold DJANGO_SECRET_KEY (to decrypt a plugin's secret settings), so tickets keyed with that could be minted
by any plugin for any project."""
import re

import yaml

from conftest import ROOT

INFRA = yaml.safe_load((ROOT / "docker-compose-infra.development.yml").read_text())["services"]
APP_FILE = yaml.safe_load((ROOT / "docker-compose.development.yml").read_text())
APP = APP_FILE["services"]
SECRETS = (ROOT / "scripts/secrets.sh").read_text()


def required(var):
    return "${%s:?run scripts/secrets.sh first}" % var


def env_of(name):
    return APP[name].get("environment") or {}


# engine_rw

def test_secrets_sh_makes_engine_rws_password():
    assert re.search(r"^ENGINE_RW_PASSWORD=rand$", SECRETS, re.M)


def test_postgres_setup_applies_it_on_every_start():
    setup = INFRA["postgres-setup"]
    assert setup["environment"]["ENGINE_RW_PASSWORD"] == required("ENGINE_RW_PASSWORD")
    assert "./init/engine-role.sql:/setup/engine-role.sql:ro,Z" in setup["volumes"]
    assert 'engine_rw_password=\\"$$ENGINE_RW_PASSWORD\\" -f /setup/engine-role.sql' in setup["command"]
    text = (ROOT / "init/engine-role.sql").read_text()
    assert "\\if :{?engine_rw_password}" in text and re.search(r"ALTER ROLE engine_rw .*PASSWORD %L", text)


def test_the_engine_logs_in_with_it():
    assert APP_FILE["x-backend-env"]["DB_PASSWORD"] == required("ENGINE_RW_PASSWORD")
    for name in ("aisc-backend", "aisc-backend-migrate"):
        assert env_of(name)["DB_PASSWORD"] == required("ENGINE_RW_PASSWORD"), name


def test_no_settings_file_carries_the_default():
    for name in ("env.plugin_downloader", "env.development"):
        assert not re.search(r"^DB_PASSWORD=engine_rw\s*$", (ROOT / name).read_text(), re.M), name


def test_the_access_check_script_reads_it():
    text = (ROOT / "scripts/verify-db-access.sh").read_text()
    assert re.search(r"engine_rw\) PW=\$\{ENGINE_RW_PASSWORD:-engine_rw\}", text)


# run tickets

def test_secrets_sh_makes_the_run_ticket_key():
    assert re.search(r"^RUN_TICKET_KEY=rand$", SECRETS, re.M)


def test_only_the_backend_holds_it():
    assert APP_FILE["x-backend-env"]["RUN_TICKET_KEY"] == required("RUN_TICKET_KEY")
    assert env_of("aisc-backend")["RUN_TICKET_KEY"] == required("RUN_TICKET_KEY")
    for name, spec in APP.items():
        if name in ("aisc-backend", "aisc-backend-migrate"):
            continue
        assert "RUN_TICKET_KEY" not in (spec.get("environment") or {}), f"{name} must not hold the ticket key"
