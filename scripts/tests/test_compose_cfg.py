"""compose_cfg resolves the stack's compose files the way the stack does: with its own settings file."""
from compose_cfg import SETTINGS, config, required, run


def test_it_reads_the_stacks_settings_file(tmp_path):
    assert SETTINGS.name == "env.plugin_downloader"
    cfg = config(tmp_path)
    # a value the stack's own settings file sets (the tests once read another file, which differed)
    assert cfg["services"]["rabbitmq"]["environment"]["RABBITMQ_DEFAULT_USER"] == "aisc-rabbit-user"


def test_every_demanded_secret_gets_a_dummy_and_profiles_and_settings_apply(tmp_path):
    assert required()
    cfg = config(tmp_path, "inspect", settings="LEDGER_MODE=off")
    assert "pgadmin" in cfg["services"]
    assert cfg["services"]["controls-web"]["environment"]["LEDGER_MODE"] == "off"
    assert run(tmp_path, quiet=True).returncode == 0


def test_a_host_variable_is_left_out_when_asked(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGER_MODE", "from-the-host")
    assert config(tmp_path)["services"]["controls-web"]["environment"]["LEDGER_MODE"] == "from-the-host"
    assert config(tmp_path, drop=("LEDGER_",))["services"]["controls-web"]["environment"]["LEDGER_MODE"] == "record"


def test_a_missing_secret_makes_compose_refuse(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_BRIDGE_TOKEN", "from-the-host")
    r = run(tmp_path, quiet=True, missing=("DASHBOARD_BRIDGE_TOKEN",))
    assert r.returncode != 0 and "DASHBOARD_BRIDGE_TOKEN" in r.stderr
