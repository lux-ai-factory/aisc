"""Caddy listens on this machine only unless the install asks for the local network (AISC_LAN=on, or served over
https), and the realm's two accounts get random passwords on every install, not admin/admin and user/user. An
install still on the known passwords is told at start which command changes them, never the value.

Read-only: scripts/aisc.py loaded as a module, compose resolved on copies of the files.
"""

import compose_cfg
from conftest import aisc_py

KNOWN = ("admin", "user")


def _host_ports(services: dict) -> list[tuple[str, str, str]]:
    return [(n, p.get("host_ip") or "0.0.0.0", str(p.get("published"))) for n, v in services.items()
            for p in v.get("ports", [])]


def test_the_accounts_get_random_passwords_on_every_install(monkeypatch):
    m = aisc_py()
    monkeypatch.setattr(m, "served_over_https", lambda: False)
    a, u = m.account("AISC_ADMIN_PASSWORD"), m.account("AISC_USER_PASSWORD")
    assert a not in KNOWN and u not in KNOWN, "an install over plain http gets admin/admin and user/user"
    assert len(a) == 64 and a != u


def test_caddy_listens_on_the_loopback_unless_the_lan_is_asked_for(monkeypatch):
    m = aisc_py()
    assert hasattr(m, "caddy_bind_address"), "scripts/aisc.py has no caddy_bind_address: Caddy listens everywhere"
    monkeypatch.setattr(m, "served_over_https", lambda: False)
    monkeypatch.delenv("AISC_LAN", raising=False)
    assert m.caddy_bind_address() == "127.0.0.1"
    monkeypatch.setenv("AISC_LAN", "on")
    assert m.caddy_bind_address() == "0.0.0.0"
    monkeypatch.setenv("AISC_LAN", "yes")
    assert m.caddy_bind_address() == "127.0.0.1"


def test_an_install_served_over_https_listens_on_the_network(monkeypatch):
    m = aisc_py()
    assert hasattr(m, "caddy_bind_address"), "scripts/aisc.py has no caddy_bind_address"
    monkeypatch.delenv("AISC_LAN", raising=False)
    monkeypatch.setattr(m, "served_over_https", lambda: True)
    assert m.caddy_bind_address() == "0.0.0.0"


def test_start_warns_an_install_still_on_the_known_account_passwords(tmp_path, capsys):
    m = aisc_py()
    assert hasattr(m, "warn_known_account_passwords"), "start says nothing to an install on admin/admin"
    secrets = tmp_path / "env.secrets"
    secrets.write_text("AISC_ADMIN_PASSWORD=admin\nAISC_USER_PASSWORD=user\n")
    m.warn_known_account_passwords(str(secrets))
    said = capsys.readouterr()
    out = said.out + said.err
    assert "rotate-infra-password AISC_ADMIN_PASSWORD" in out
    assert "=admin" not in out and "=user" not in out


def test_the_browser_ports_are_on_the_loopback_by_default(tmp_path):
    services = compose_cfg.config(tmp_path)["services"]
    open_ports = sorted((n, h, p) for n, h, p in _host_ports(services) if h != "127.0.0.1")
    assert open_ports == [], "published on every interface"


def test_the_lan_setting_opens_caddy_only(tmp_path):
    services = compose_cfg.config(tmp_path, env={"CADDY_BIND_ADDRESS": "0.0.0.0"})["services"]
    opened = {(n, h) for n, h, _ in _host_ports(services) if h == "0.0.0.0"}
    assert opened == {("caddy", "0.0.0.0")}
