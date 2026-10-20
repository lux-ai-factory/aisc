"""The engine's database role and its run tickets.

engine_rw's password is generated, not its own name (as controls_rw's): the engine connects to every project
database. Its run tickets, which bind a plugin's calls back into the engine to its own project and evaluation,
are keyed with RUN_TICKET_KEY, which only the backend holds: the eval worker runs third-party plugin code and
must hold DJANGO_SECRET_KEY (to decrypt a plugin's secret settings), so tickets keyed with that could be minted
by any plugin for any project."""
import re

import yaml

from conftest import ROOT, aisc_py

APP_FILE = yaml.safe_load((ROOT / "docker-compose.development.yml").read_text())
APP = APP_FILE["services"]
SECRETS = dict(aisc_py().SECRETS)


def required(var):
    return "${%s:?run scripts/secrets.sh first}" % var


def env_of(name):
    return APP[name].get("environment") or {}


# engine_rw

def test_the_engine_logs_in_with_it():
    assert APP_FILE["x-backend-env"]["DB_PASSWORD"] == required("ENGINE_RW_PASSWORD")
    for name in ("aisc-backend", "aisc-backend-migrate"):
        assert env_of(name)["DB_PASSWORD"] == required("ENGINE_RW_PASSWORD"), name


def test_no_settings_file_carries_the_default():
    assert not re.search(r"^DB_PASSWORD=engine_rw\s*$", (ROOT / "env.plugin_downloader").read_text(), re.M)


# run tickets

def test_secrets_sh_makes_the_run_ticket_key():
    assert SECRETS["RUN_TICKET_KEY"] == "rand"


def test_only_the_backend_holds_it():
    assert APP_FILE["x-backend-env"]["RUN_TICKET_KEY"] == required("RUN_TICKET_KEY")
    assert env_of("aisc-backend")["RUN_TICKET_KEY"] == required("RUN_TICKET_KEY")
    for name, spec in APP.items():
        # the migration and the ledger's deliverer run no plugin code; the configurator's start-up check
        # (aisc_backend/deployment.py) refuses any engine process without the key
        if name in ("aisc-backend", "aisc-backend-migrate", "aisc-backend-ledger"):
            continue
        assert "RUN_TICKET_KEY" not in (spec.get("environment") or {}), f"{name} must not hold the ticket key"
