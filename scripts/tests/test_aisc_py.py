"""scripts/aisc.py run as the README runs it, `uv run scripts/aisc.py ...`, with no bash and no Unix tools. These
run on Linux and on CI's Windows runner, so what the script does with paths, files and line endings is checked on
both. uv brings the script's own Python and library, whatever the tests run on.

    uv run --no-project --with pytest python -m pytest -q scripts/tests/test_aisc_py.py
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys

import pytest

from conftest import ROOT, aisc_py, copy_install_scripts


#: found once, before a test empties PATH to take Docker away
UV = shutil.which("uv")


def install(tmp_path):
    copy_install_scripts(tmp_path)
    shutil.copy(ROOT / "env.plugin_downloader", tmp_path / "env.plugin_downloader")
    return tmp_path


def run(d, *args, path=None, stdin=None, **env_over):
    env = {**os.environ, **env_over}
    env.pop("CADDY_DOMAIN", None)
    if path is not None:
        env["PATH"] = path
    return subprocess.run([UV, "run", "--quiet", "--script", str(d / "scripts/aisc.py"), *args], cwd=d, env=env,
                          capture_output=True, text=True, timeout=300, input=stdin)


def values(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line and not line.startswith("#"))


def test_secrets_makes_every_secret_the_runtime_env_and_the_signing_key(tmp_path):
    d = install(tmp_path)
    r = run(d, "secrets")
    assert r.returncode == 0, r.stderr
    made = values(d / "env.secrets")
    assert [name for name in made if name != "AISC_INSTALL"] == [name for name, _ in aisc_py().SECRETS]
    assert all(made.values()), "an empty secret"
    assert made["AISC_ADMIN_PASSWORD"] == "admin" and made["AISC_USER_PASSWORD"] == "user"
    assert len(made["GATEWAY_COOKIE_SECRET"]) == 43 and len(made["PLATFORM_SECRETS_KEY"]) == 44
    runtime = values(d / "env.runtime")
    assert {k: runtime[k] for k in made} == made
    assert "PRIVATE KEY" in (d / "immudb-signing.key").read_text()
    assert "PUBLIC KEY" in (d / "immudb-signing.pub").read_text()


def test_the_files_it_writes_have_linux_line_endings_on_every_system(tmp_path):
    """compose and the containers read them: a Windows CRLF would end up inside every value."""
    d = install(tmp_path)
    assert run(d, "secrets").returncode == 0
    for name in ("env.secrets", "env.runtime"):
        assert b"\r\n" not in (d / name).read_bytes(), name


def test_a_second_run_keeps_every_value(tmp_path):
    d = install(tmp_path)
    assert run(d, "secrets").returncode == 0
    before = (d / "env.secrets").read_text()
    r = run(d, "secrets")
    assert r.returncode == 0, r.stderr
    assert (d / "env.secrets").read_text() == before


def test_password_shows_the_accounts_of_this_install(tmp_path):
    d = install(tmp_path)
    assert run(d, "secrets").returncode == 0
    r = run(d, "password")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["admin", "admin", "user", "user"]


def test_password_before_any_secret_says_what_to_run(tmp_path):
    r = run(install(tmp_path), "password")
    assert r.returncode == 1 and "aisc.py secrets" in r.stderr


def test_start_without_docker_says_so_and_writes_nothing(tmp_path):
    d = install(tmp_path)
    empty = tmp_path / "no-tools"
    empty.mkdir()
    r = run(d, "start", path=str(empty))
    assert r.returncode == 1
    assert "Docker is not running" in r.stderr and "Docker Desktop" in r.stderr
    assert not (d / "env.secrets").exists()


def test_docker_is_looked_for_on_the_path_this_process_has(tmp_path, monkeypatch):
    """Windows finds a program through the parent process's search path, not the PATH given to a child, so
    `docker info` can succeed for a person with no Docker on their PATH. The command is looked up on PATH
    itself, once, and the path found is what every call uses."""
    empty = tmp_path / "no-tools"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert aisc_py().find_docker() is None
    fake = tmp_path / "tools"
    fake.mkdir()
    name = "docker.exe" if os.name == "nt" else "docker"
    (fake / name).write_text("#!/bin/sh\n")
    (fake / name).chmod(0o755)
    monkeypatch.setenv("PATH", str(fake))
    assert os.path.samefile(aisc_py().find_docker(), fake / name)


def test_the_realm_is_polled_on_keycloaks_local_port_whatever_its_public_address(tmp_path, monkeypatch):
    """An https or other-host install's public name may not resolve from the machine running start (hairpin
    NAT, a self-signed certificate), so the wait uses Keycloak's own published port on this machine."""
    m = aisc_py()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("START_SIGN_IN_URL", raising=False)
    (tmp_path / "env.runtime").write_text('KEYCLOAK_URL_EXTERNAL="https://aisc.example.org"\n')
    assert m.keycloak_realm_url() == "http://localhost:8081/realms/aisc"
    (tmp_path / "env.runtime").write_text('KEYCLOAK_PORT_EXTERNAL=8090\nKEYCLOAK_URL_EXTERNAL="https://x.org"\n'
                                          'KEYCLOAK_PORT_EXTERNAL="8091"\n')
    assert m.keycloak_realm_url() == "http://localhost:8091/realms/aisc"
    monkeypatch.setenv("START_SIGN_IN_URL", "http://elsewhere/realms/aisc")
    assert m.keycloak_realm_url() == "http://elsewhere/realms/aisc"


def test_rotating_without_docker_on_the_path_is_refused_and_changes_nothing(tmp_path):
    d = install(tmp_path)
    assert run(d, "secrets").returncode == 0
    before = (d / "env.secrets").read_text()
    empty = tmp_path / "no-tools"
    empty.mkdir()
    r = run(d, "rotate-infra-password", "POSTGRES_PASSWORD", path=str(empty))
    assert r.returncode != 0
    assert "Docker is not running" in r.stderr
    assert (d / "env.secrets").read_text() == before


def test_an_unknown_command_shows_the_usage(tmp_path):
    r = run(install(tmp_path), "install")
    assert r.returncode == 2 and "start|secrets|password|rotate-infra-password" in r.stderr


def test_rotating_an_unknown_name_is_refused_before_docker_is_asked(tmp_path):
    d = install(tmp_path)
    assert run(d, "secrets").returncode == 0
    before = (d / "env.secrets").read_text()
    r = run(d, "rotate-infra-password", "DJANGO_SECRET_KEY")
    assert r.returncode == 2 and "usage" in r.stderr
    assert (d / "env.secrets").read_text() == before


# The ports: a taken one is tested before anything is built, and a taken browser port moves to a free one

def test_a_taken_port_falls_back_to_the_first_free_one():
    m = aisc_py()
    assert m.choose_port(80, (8080, 8090), lambda p: p == 8090) == 8090
    assert m.choose_port(80, (8080, 8090), lambda p: True) == 80
    assert m.choose_port(80, (8080, 8090), lambda p: False) is None


def test_an_address_drops_the_default_port():
    """Browsers send the Origin of http://localhost:80 as http://localhost: the address must match it. The
    launcher's address ends with a slash, as LAUNCHER_EXTERNAL_URL always has."""
    m = aisc_py()
    engine, launcher = role("ENGINE_PORT"), role("HOMEPAGE_PORT_EXTERNAL")
    assert m.address_of(engine, 80) == "http://localhost"
    assert m.address_of(engine, 8080) == "http://localhost:8080"
    assert m.address_of(launcher, 8110) == "http://localhost:8110/"


def test_a_port_someone_listens_on_is_not_free():
    m = aisc_py()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        assert not m.port_is_free(port, "127.0.0.1")
    assert m.port_is_free(port, "127.0.0.1")


def test_a_port_below_1024_without_root_is_judged_by_connecting(monkeypatch):
    """Linux refuses the bind itself without root; then whether something answers decides."""
    m = aisc_py()

    def refused(self, address):
        raise PermissionError(13, "Permission denied")

    with socket.socket() as s:   # a real listener, bound before bind is refused
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        monkeypatch.setattr(socket.socket, "bind", refused)
        assert not m.port_is_free(port, "0.0.0.0")
        monkeypatch.undo()
    monkeypatch.setattr(socket.socket, "bind", refused)
    assert m.port_is_free(port, "0.0.0.0")


def test_a_listener_on_the_machines_other_address_is_taken_below_1024(monkeypatch):
    """Without root Linux refuses the bind; a program listening on the machine's network address only (not on
    127.0.0.1) must still count, or Docker fails to publish the port."""
    m = aisc_py()

    def refused(self, address):
        raise PermissionError(13, "Permission denied")

    other = "127.0.0.2"   # stands for the machine's network address: a loopback address of its own
    with socket.socket() as s:
        try:
            s.bind((other, 0))
        except OSError:
            pytest.skip("this system cannot bind 127.0.0.2")
        s.listen()
        port = s.getsockname()[1]
        monkeypatch.setattr(socket.socket, "bind", refused)
        monkeypatch.setattr(socket, "getaddrinfo",
                            lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (other, 0))])
        assert not m.port_is_free(port, "0.0.0.0")


def test_the_runtime_env_takes_the_install_settings_last(tmp_path):
    """env.local holds what start chose for this install; the by-hand path (secrets, then compose) keeps it."""
    d = install(tmp_path)
    assert run(d, "secrets").returncode == 0
    (d / "env.local").write_text("API_URL_EXTERNAL=http://localhost:8080\nENGINE_PORT=8080\n")
    r = run(d, "secrets")
    assert r.returncode == 0, r.stderr
    lines = (d / "env.runtime").read_text().splitlines()
    assert lines[-3:-1] == ["API_URL_EXTERNAL=http://localhost:8080", "ENGINE_PORT=8080"]
    assert lines[-1].startswith("CONTAINER_PREFIX=aisc-")


#: what docker compose config publishes, in settle_ports' terms: (service, address, published port, container port)
PUBLISHED = [("caddy", "0.0.0.0", 80, 8005), ("caddy", "0.0.0.0", 443, 8005), ("caddy", "0.0.0.0", 8100, 8006),
             ("caddy", "0.0.0.0", 8188, 8008), ("keycloak", "127.0.0.1", 8081, 8080),
             ("postgres", "127.0.0.1", 5432, 5432)]
FALLBACKS_OF_80 = (8080, 8090, 8000, 8880, 8888)
EVERY_PORT_AT_HOME = {"ENGINE_PORT": "80", "HOMEPAGE_PORT_EXTERNAL": "8100", "DASHBOARD_PORT_EXTERNAL": "8188",
                      "KEYCLOAK_PORT_EXTERNAL": "8081"}


def taken(*ports):
    return lambda port, host: port not in ports


def role(variable):
    return next(port for port in aisc_py().BROWSER_PORTS if port.variable == variable)


def test_a_new_install_moves_off_a_taken_port_80():
    settings, problems, _moved = aisc_py().settle_ports(PUBLISHED, set(), {}, True, taken(80))
    assert problems == []
    assert settings["ENGINE_PORT"] == "8080" and settings["API_URL_EXTERNAL"] == "http://localhost:8080"


def test_every_browser_port_may_move_on_an_install_with_data():
    """The sign-in is told the install's addresses on every start, so data is no reason to stay on a taken port."""
    settings, problems, _moved = aisc_py().settle_ports(PUBLISHED, set(), {}, True, taken(8100))
    assert problems == []
    assert settings["HOMEPAGE_PORT_EXTERNAL"] == "8110"
    assert settings["LAUNCHER_EXTERNAL_URL"] == "http://localhost:8110/"


def test_the_sign_in_port_moves_with_its_address():
    settings, problems, _moved = aisc_py().settle_ports(PUBLISHED, set(), {}, True, taken(8081))
    assert problems == []
    assert settings["KEYCLOAK_PORT_EXTERNAL"] == "8091"
    assert settings["KEYCLOAK_URL_EXTERNAL"] == "http://localhost:8091"


def test_two_roles_never_share_a_port():
    """No fallback is listed twice or is another role's preferred port, and a port picked for one role is not
    offered to the next, not even when this install kept it for that one."""
    m = aisc_py()
    offered = [p for port in m.BROWSER_PORTS for p in port.fallbacks]
    preferred = [port.preferred for port in m.BROWSER_PORTS]
    assert len(offered) == len(set(offered)) and len(preferred) == len(set(preferred))
    assert not set(offered) & set(preferred)

    def free(port, host):
        return port not in (80, 8080)

    settings, problems, _moved = m.settle_ports(PUBLISHED, set(), {"HOMEPAGE_PORT_EXTERNAL": "8090"}, True, free)
    assert problems == []
    assert settings["ENGINE_PORT"] == "8090"
    others = [value for name, value in settings.items() if name != "ENGINE_PORT" and name.endswith("PORT_EXTERNAL")]
    assert "8090" not in others


def test_an_https_install_never_moves():
    """Its addresses are its own public names: a port that moved would not be reached through them."""
    m = aisc_py()
    settings, problems, moved = m.settle_ports(PUBLISHED, set(), {}, False, taken(8100))
    assert len(problems) == 1 and "8100" in problems[0] and m.who_holds(8100) in problems[0]
    assert "LAUNCHER_EXTERNAL_URL" not in settings and moved == []


def test_an_https_install_keeps_its_ports_but_never_gets_a_local_address():
    """A port kept from a start on plain http stays published, but env.local comes last in env.runtime: a
    localhost address written there would override the install's public https names and break its sign-in."""
    m = aisc_py()
    settings, problems, _moved = m.settle_ports(PUBLISHED, set(), {"HOMEPAGE_PORT_EXTERNAL": "8110"}, False, taken())
    assert problems == [] and settings["HOMEPAGE_PORT_EXTERNAL"] == "8110"
    assert "LAUNCHER_EXTERNAL_URL" not in settings
    settings, problems, _moved = m.settle_ports(PUBLISHED, set(), {"ENGINE_PORT": "8090"}, False, taken())
    assert problems == [] and settings["ENGINE_PORT"] == "8090"
    assert "API_URL_EXTERNAL" not in settings


def test_with_every_port_free_nothing_changes():
    settings, problems, moved = aisc_py().settle_ports(PUBLISHED, set(), {}, True, taken())
    assert problems == [] and moved == []
    assert settings == EVERY_PORT_AT_HOME


def test_ports_held_by_aisc_itself_are_not_taken():
    """A second start finds its own stack on its ports: that is not a reason to move."""
    own = {80, 443, 8100, 8188, 8081, 5432}
    settings, problems, moved = aisc_py().settle_ports(PUBLISHED, own, {}, False, taken(*own))
    assert problems == [] and moved == []
    assert settings == EVERY_PORT_AT_HOME


def test_a_moved_port_is_tried_first_next_time():
    """A port that moved stays where it went, even once its preferred one is free again."""
    kept = {"ENGINE_PORT": "8090", "API_URL_EXTERNAL": "http://localhost:8090", "HOMEPAGE_PORT_EXTERNAL": "8100"}
    settings, problems, moved = aisc_py().settle_ports(PUBLISHED, set(), kept, True, taken())
    assert problems == [] and moved == []
    assert settings["ENGINE_PORT"] == "8090" and settings["API_URL_EXTERNAL"] == "http://localhost:8090"


def test_a_kept_port_taken_later_moves_again():
    kept = {"ENGINE_PORT": "8090", "API_URL_EXTERNAL": "http://localhost:8090"}
    settings, problems, moved = aisc_py().settle_ports(PUBLISHED, set(), kept, True, taken(8090))
    assert problems == [] and settings["ENGINE_PORT"] == "80" and "API_URL_EXTERNAL" not in settings
    assert len(moved) == 1 and "8090" in moved[0]


def test_a_kept_port_taken_later_stops_an_https_install():
    kept = {"ENGINE_PORT": "8090", "API_URL_EXTERNAL": "http://localhost:8090"}
    settings, problems, _moved = aisc_py().settle_ports(PUBLISHED, set(), kept, False, taken(8090))
    assert len(problems) == 1 and "8090" in problems[0]


def test_every_fallback_taken_stops_start():
    settings, problems, _moved = aisc_py().settle_ports(PUBLISHED, set(), {}, True, taken(80, *FALLBACKS_OF_80))
    assert len(problems) == 1
    assert all(str(p) in problems[0] for p in (80, *FALLBACKS_OF_80))


def test_a_move_is_reported_once():
    """One line per port that moved this start, naming the taken port and the address that replaces it."""
    m = aisc_py()
    _settings, _problems, moved = m.settle_ports(PUBLISHED, set(), {}, True, taken(8100, 8188))
    assert len(moved) == 2
    assert "8100" in moved[0] and "http://localhost:8110/" in moved[0]
    assert "8188" in moved[1] and "http://localhost:8198" in moved[1]
    assert m.settle_ports(PUBLISHED, set(), {}, True, taken())[2] == []


def test_other_taken_ports_are_named_with_their_holder_command():
    m = aisc_py()
    settings, problems, _moved = m.settle_ports(PUBLISHED, set(), {}, True, taken(5432))
    assert len(problems) == 1 and "5432" in problems[0] and m.who_holds(5432) in problems[0]


def test_a_taken_https_port_is_still_named():
    """443 is Caddy's too, but no browser port moves there: a taken one stops the start as before."""
    settings, problems, _moved = aisc_py().settle_ports(PUBLISHED, set(), {}, True, taken(443))
    assert len(problems) == 1 and "443" in problems[0]


def test_an_address_no_longer_needed_leaves_env_local():
    """Back on its preferred port, a role's address in env.local would override the install's own."""
    m = aisc_py()
    existing = ["# mine", "HOMEPAGE_PORT_EXTERNAL=8110", "LAUNCHER_EXTERNAL_URL=http://localhost:8110/", "MY=x"]
    assert m.local_lines(existing, {"HOMEPAGE_PORT_EXTERNAL": "8100"}) == [
        "# mine", "HOMEPAGE_PORT_EXTERNAL=8100", "MY=x"]


def test_published_ports_reads_compose_config():
    config = {"services": {"caddy": {"ports": [{"published": "80", "target": 8005}]},
                           "postgres": {"ports": [{"host_ip": "127.0.0.1", "published": "5432", "target": 5432}]},
                           "platform": {}}}
    assert aisc_py().published_ports(config) == [("caddy", "0.0.0.0", 80, 8005),
                                                 ("postgres", "127.0.0.1", 5432, 5432)]


def test_the_project_name_can_be_set(tmp_path, monkeypatch):
    """A second copy beside an existing install's data runs under its own name. On a scratch copy: the checkout's
    own env.secrets may hold an install id."""
    copy_install_scripts(tmp_path)
    monkeypatch.delenv("AISC_PROJECT", raising=False)
    assert aisc_py(tmp_path).COMPOSE[:4] == ["docker", "compose", "-p", "aisc"]
    (tmp_path / "env.secrets").write_text("AISC_INSTALL=a1b2c3\n")
    assert aisc_py(tmp_path).COMPOSE[:4] == ["docker", "compose", "-p", "aisc-a1b2c3"]
    monkeypatch.setenv("AISC_PROJECT", "aisc-proof")
    assert aisc_py(tmp_path).COMPOSE[:4] == ["docker", "compose", "-p", "aisc-proof"]


def test_compose_adds_the_https_file_only_for_https(tmp_path, monkeypatch):
    """443 is published only by an install served over https: elsewhere a taken 443 must not stop a start.
    On a scratch copy: the checkout's own env.local may ask for the admin ports."""
    copy_install_scripts(tmp_path)
    monkeypatch.delenv("AISC_ADMIN_PORTS", raising=False)
    monkeypatch.setenv("CADDY_DOMAIN", "http://localhost")
    assert "docker-compose.https.yml" not in aisc_py(tmp_path).COMPOSE
    assert "docker-compose.https.yml" not in aisc_py(tmp_path).up_hint()
    monkeypatch.setenv("CADDY_DOMAIN", "https://x")
    module = aisc_py(tmp_path)
    assert module.COMPOSE[-2:] == ["-f", "docker-compose.https.yml"]
    assert "-f docker-compose.https.yml" in module.up_hint()


def test_compose_adds_the_admin_ports_file_only_when_asked(tmp_path, monkeypatch):
    copy_install_scripts(tmp_path)
    monkeypatch.setenv("CADDY_DOMAIN", "http://localhost")
    monkeypatch.delenv("AISC_ADMIN_PORTS", raising=False)
    assert "docker-compose.admin-ports.yml" not in aisc_py(tmp_path).COMPOSE
    monkeypatch.setenv("AISC_ADMIN_PORTS", "on")
    module = aisc_py(tmp_path)
    assert module.COMPOSE[-2:] == ["-f", "docker-compose.admin-ports.yml"]
    assert "-f docker-compose.admin-ports.yml" in module.up_hint()


def test_the_admin_ports_may_be_asked_for_in_env_local(tmp_path, monkeypatch):
    """env.local holds this install's own settings, so asking for the infrastructure's ports there counts too."""
    monkeypatch.setenv("CADDY_DOMAIN", "http://localhost")
    monkeypatch.delenv("AISC_ADMIN_PORTS", raising=False)
    copy_install_scripts(tmp_path)
    assert "docker-compose.admin-ports.yml" not in aisc_py(tmp_path).COMPOSE
    (tmp_path / "env.local").write_text('AISC_ADMIN_PORTS=off\nAISC_ADMIN_PORTS="on"\n')
    assert "docker-compose.admin-ports.yml" in aisc_py(tmp_path).COMPOSE
    (tmp_path / "env.local").write_text("AISC_ADMIN_PORTS=on\nAISC_ADMIN_PORTS=off\n")
    assert "docker-compose.admin-ports.yml" not in aisc_py(tmp_path).COMPOSE


def test_the_shell_setting_of_the_admin_ports_wins_over_env_local(tmp_path, monkeypatch):
    monkeypatch.setenv("CADDY_DOMAIN", "http://localhost")
    copy_install_scripts(tmp_path)
    (tmp_path / "env.local").write_text("AISC_ADMIN_PORTS=on\n")
    monkeypatch.setenv("AISC_ADMIN_PORTS", "off")
    assert "docker-compose.admin-ports.yml" not in aisc_py(tmp_path).COMPOSE


def test_a_port_whose_closed_connections_are_still_waiting_is_free():
    """Linux keeps a closed connection in TIME_WAIT for a minute; Docker binds over it, so the check must too.
    The server here sets SO_REUSEADDR, as Caddy and Docker's port proxy do (every Go listener does): only then
    may a new bind pass its waiting connections."""
    m = aisc_py()
    with socket.socket() as listening:
        listening.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listening.bind(("127.0.0.1", 0))
        listening.listen()
        port = listening.getsockname()[1]
        client = socket.create_connection(("127.0.0.1", port))
        accepted, _ = listening.accept()
        accepted.close()                     # the server side closes first: its end waits in TIME_WAIT
        client.close()
    assert m.port_is_free(port, "127.0.0.1")


def test_address_reuse_is_set_on_linux_only(monkeypatch):
    """On macOS (BSD sockets) SO_REUSEADDR lets a bind on 0.0.0.0 succeed beside a program listening on
    127.0.0.1 only, so such a port would read as free."""
    m = aisc_py()
    options = []
    plain = socket.socket.setsockopt

    def record(self, level, option, *value):
        options.append(option)
        return plain(self, level, option, *value)

    monkeypatch.setattr(socket.socket, "setsockopt", record)
    for platform, expected in (("darwin", False), ("linux", True)):
        options.clear()
        monkeypatch.setattr(sys, "platform", platform)
        m.port_is_free(0, "127.0.0.1")
        assert (socket.SO_REUSEADDR in options) is expected, platform


def test_a_reserved_port_on_windows_is_taken(monkeypatch):
    """Windows refuses a bind on its reserved ranges (Hyper-V, WSL) with an access error: Docker cannot use
    the port either, whatever answers a connect."""
    m = aisc_py()

    def refused(self, address):
        raise PermissionError(10013, "access forbidden")

    monkeypatch.setattr(socket.socket, "bind", refused)
    monkeypatch.setattr(m.os, "name", "nt")
    assert not m.port_is_free(51234, "0.0.0.0")


def test_the_sign_in_clients_list_exactly_the_install_s_addresses():
    """What start sends Keycloak on every start: the gateway's callbacks on the three addresses it serves, and
    the webapp's own, with the frontend's development server (5173) kept."""
    clients = aisc_py().sign_in_clients("http://localhost:8080", "http://localhost:8110/", "http://localhost:8198")
    assert clients == {
        "aisc-gateway": {
            "redirectUris": ["http://localhost:8080/oauth2/callback", "http://localhost:8110/oauth2/callback",
                             "http://localhost:8198/oauth2/callback"],
            "webOrigins": ["+"],
            "attributes": {"post.logout.redirect.uris": "http://localhost:8110/*##http://localhost:8080/*"},
        },
        "aisc-webapp": {
            "baseUrl": "http://localhost:8080",
            "redirectUris": ["http://localhost:8080/*", "http://localhost:5173/*"],
            "webOrigins": ["http://localhost:8080", "http://localhost:5173"],
        },
    }


def test_an_https_install_s_sign_in_uses_its_own_addresses():
    clients = aisc_py().sign_in_clients("https://aisc.example.org", "https://aisc.example.org:8100/",
                                        "https://aisc.example.org:8188", over_https=True)
    gateway, webapp = clients["aisc-gateway"], clients["aisc-webapp"]
    assert gateway["redirectUris"] == ["https://aisc.example.org/oauth2/callback",
                                       "https://aisc.example.org:8100/oauth2/callback",
                                       "https://aisc.example.org:8188/oauth2/callback"]
    assert gateway["attributes"]["post.logout.redirect.uris"] == \
        "https://aisc.example.org:8100/*##https://aisc.example.org/*"
    assert webapp["baseUrl"] == "https://aisc.example.org"
    # the frontend's development server is a developer's own machine: a public install's sign-in has no part
    # of it (aisc-webapp is a public client)
    assert webapp["redirectUris"] == ["https://aisc.example.org/*"]
    assert webapp["webOrigins"] == ["https://aisc.example.org"]


def test_kcadm_is_given_no_secret_on_its_command_line():
    """kcadm starts Java with its arguments, which the host's `ps` shows: the admin's password comes from
    KC_CLI_PASSWORD (kcadm reads it itself) and no password is an argument."""
    m = aisc_py()
    assert "--password" not in m.KCADM_RUN and "--new-password" not in m.KCADM_RUN
    assert "VALUE" not in m.KCADM_RUN and "KC_CLI_PASSWORD" not in m.KCADM_RUN


def test_a_launcher_address_without_its_slash_gets_one():
    """Without it the sign-out rule https://app.example.com* also matches https://app.example.com.attacker.net/
    (an open redirect), and the callback becomes ...comoauth2/callback."""
    gateway = aisc_py().sign_in_clients("https://app.example.com:8443", "https://app.example.com",
                                        "https://app.example.com:8188")["aisc-gateway"]
    assert "https://app.example.com/oauth2/callback" in gateway["redirectUris"]
    assert gateway["attributes"]["post.logout.redirect.uris"].split("##")[0] == "https://app.example.com/*"


def test_every_kcadm_run_has_a_session_file_of_its_own():
    """A shared session file would let a rotate running beside a start remove the other's session: each run
    makes its own (mktemp) and removes it on exit. The script runs in Keycloak's container."""
    script = aisc_py().KCADM_RUN
    assert "mktemp" in script and "trap " in script
    assert not re.search(r"/tmp/[\w.-]", script)


@pytest.mark.parametrize("message", [
    "Error response from daemon: ports are not available: exposing port TCP 0.0.0.0:80 -> 127.0.0.1:0: "
    "/forwards/expose returned unexpected status: 500",
    "Bind for 0.0.0.0:80 failed: port is already allocated",
    "Error starting userland proxy: listen tcp4 0.0.0.0:80: bind: address already in use",
    "listen tcp 0.0.0.0:80: bind: An attempt was made to access a socket in a way forbidden by its access "
    "permissions.",
    "PORTS ARE NOT AVAILABLE: exposing port TCP 0.0.0.0:80",
    "listen tcp 0.0.0.0:80: bind: Only one usage of each socket address (protocol/network address/port) is "
    "normally permitted.",
])
def test_docker_s_refusals_of_a_taken_port_are_recognised(message):
    assert aisc_py().docker_says_port_taken(message)


@pytest.mark.parametrize("message", [
    "Unable to find image 'caddy:2.10.2' locally\npull access denied for caddy",
    "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?",
    "",
])
def test_other_docker_errors_say_nothing_of_the_port(message):
    assert not aisc_py().docker_says_port_taken(message)


def test_the_probe_answers_free_taken_or_cannot_tell(monkeypatch):
    """Docker publishing the port means free; refusing it as taken means taken; any other failure, or a probe
    that hangs, cannot tell (None), and the host's own check decides."""
    m = aisc_py()
    answers = {}

    def docker(argv, **_kwargs):
        if argv[1] == "run":
            if answers["run"] == "hangs":
                raise subprocess.TimeoutExpired(argv, 1)
            code, err = answers["run"]
            return subprocess.CompletedProcess(argv, code, "", err)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(m.subprocess, "run", docker)
    answers["run"] = (0, "")
    assert m.docker_can_publish(80, "0.0.0.0") is True
    answers["run"] = (125, "Bind for 0.0.0.0:80 failed: port is already allocated")
    assert m.docker_can_publish(80, "0.0.0.0") is False
    answers["run"] = (125, "pull access denied for caddy")
    assert m.docker_can_publish(80, "0.0.0.0") is None
    answers["run"] = "hangs"
    assert m.docker_can_publish(80, "0.0.0.0") is None


def test_a_port_docker_refuses_is_explained_as_docker_s_not_the_host_s():
    """The host's tools cannot see a port taken inside Docker Desktop or WSL: the advice is Docker's."""
    m = aisc_py()
    windows, elsewhere = m.docker_side_hint(windows=True), m.docker_side_hint(windows=False)
    assert "wsl --shutdown" in windows and "Docker Desktop" in windows and "netstat" not in windows
    assert "restarting Docker" in elsewhere and "lsof" not in elsewhere
    _settings, problems, _moved = m.settle_ports(PUBLISHED, set(), {}, False, taken(80),
                                                 taken_in_docker=lambda port: port == 80)
    assert len(problems) == 1 and "Docker cannot use it" in problems[0] and m.who_holds(80) not in problems[0]
    _settings, _problems, moved = m.settle_ports(PUBLISHED, set(), {}, True, taken(80),
                                                 taken_in_docker=lambda port: port == 80)
    assert moved and moved[0].startswith("Port 80 is taken (Docker cannot use it), so AISC uses")
    _settings, problems, moved = m.settle_ports(PUBLISHED, set(), {}, True, taken(80))
    assert moved[0].startswith("Port 80 is taken on this computer")


def test_a_probe_that_hangs_stops_further_probes(monkeypatch):
    m = aisc_py()
    runs = []

    def docker(argv, **_kwargs):
        if argv[1] == "run":
            runs.append(argv)
            raise subprocess.TimeoutExpired(argv, 1)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(m.subprocess, "run", docker)
    assert m.docker_can_publish(80, "0.0.0.0") is None
    assert m.docker_can_publish(8100, "0.0.0.0") is None
    assert len(runs) == 1


def test_a_new_checkout_gets_its_own_install_id(tmp_path):
    d = install(tmp_path)
    assert run(d, "secrets").returncode == 0
    first = values(d / "env.secrets")["AISC_INSTALL"]
    assert re.fullmatch(r"[0-9a-f]{6}", first)
    assert values(d / "env.runtime")["CONTAINER_PREFIX"] == f"aisc-{first}-"
    assert run(d, "secrets").returncode == 0
    assert values(d / "env.secrets")["AISC_INSTALL"] == first
    assert run(d, "secrets", "--rotate").returncode == 0
    assert values(d / "env.secrets")["AISC_INSTALL"] == first


def test_an_existing_install_keeps_the_shared_names(tmp_path):
    d = install(tmp_path)
    run(d, "secrets")
    text = (d / "env.secrets").read_text()
    (d / "env.secrets").write_text("\n".join(l for l in text.splitlines() if not l.startswith("AISC_INSTALL=")) + "\n")
    assert run(d, "secrets").returncode == 0
    assert "AISC_INSTALL" not in values(d / "env.secrets")
    assert values(d / "env.runtime").get("CONTAINER_PREFIX", "") == ""


def test_an_empty_install_id_is_made_again(tmp_path):
    d = install(tmp_path)
    run(d, "secrets")
    text = (d / "env.secrets").read_text()
    (d / "env.secrets").write_text(re.sub(r"AISC_INSTALL=\w+", "AISC_INSTALL=", text))
    assert run(d, "secrets").returncode == 0
    assert re.fullmatch(r"[0-9a-f]{6}", values(d / "env.secrets")["AISC_INSTALL"])


def test_the_stack_name_follows_the_install(monkeypatch):
    m = aisc_py()
    monkeypatch.delenv("AISC_PROJECT", raising=False)
    assert m.stack_name("a1b2c3") == "aisc-a1b2c3"
    assert m.stack_name("") == "aisc"
    assert m.container_prefix("a1b2c3") == "aisc-a1b2c3-"
    assert m.container_prefix("") == ""
    monkeypatch.setenv("AISC_PROJECT", "aisc-ports")
    assert m.stack_name("a1b2c3") == "aisc-ports"
    assert m.container_prefix("a1b2c3") == "aisc-a1b2c3-"


def test_only_other_stacks_count_as_another_install():
    m = aisc_py()
    ps = "aisc\t/home/a/aisc\naisc-a1b2c3\t/home/a/new\naisc\t/home/a/aisc\n"
    assert m.other_stacks(ps, "aisc-a1b2c3") == [("aisc", "/home/a/aisc")]
    assert m.other_stacks(ps.replace("aisc\t", "aisc-a1b2c3\t"), "aisc-a1b2c3") == []


def test_the_refusal_names_the_folder_and_keeps_the_data():
    text = aisc_py().another_install_refusal("aisc", "/home/a/aisc")
    assert "/home/a/aisc" in text and "docker compose -p aisc stop" in text and "data" in text


PS_OBJECTS = [
    {"Service": "minio", "State": "running", "Health": "unhealthy", "ExitCode": 0},
    {"Service": "make_buckets", "State": "exited", "Health": "", "ExitCode": 0},
    {"Service": "postgres-setup", "State": "exited", "Health": "", "ExitCode": 1},
    {"Service": "aisc-backend", "State": "created", "Health": "", "ExitCode": 0},
]


def test_unhealthy_and_failed_services_are_found(tmp_path):
    """Compose prints one object per line (newer) or one array (older): both name the same services."""
    copy_install_scripts(tmp_path)
    module = aisc_py(tmp_path)
    per_line = "\n".join(json.dumps(o) for o in PS_OBJECTS)
    assert module.failing_services(per_line) == ["minio", "postgres-setup"]
    assert module.failing_services(json.dumps(PS_OBJECTS)) == ["minio", "postgres-setup"]
    assert module.failing_services("") == []
    assert module.failing_services("not json") == []


def test_a_log_docker_does_not_answer_still_ends_in_the_refusal(tmp_path, monkeypatch):
    copy_install_scripts(tmp_path)
    module = aisc_py(tmp_path)
    monkeypatch.setattr(module, "docker_in_time", lambda argv, wait_s: None)
    module.show_failing_logs()   # returns, prints nothing it cannot get


def test_the_failing_services_last_lines_are_shown(tmp_path, monkeypatch, capsys):
    copy_install_scripts(tmp_path)
    module = aisc_py(tmp_path)
    asked = []

    def answer(argv, wait_s):
        asked.append(argv)
        if "ps" in argv:
            return subprocess.CompletedProcess(argv, 0, "\n".join(json.dumps(o) for o in PS_OBJECTS), "")
        return subprocess.CompletedProcess(argv, 0, f"found invalid keys ({argv[-1]})\n", "")

    monkeypatch.setattr(module, "docker_in_time", answer)
    module.show_failing_logs()
    err = capsys.readouterr().err
    assert "minio" in err and "found invalid keys (minio)" in err and "found invalid keys (postgres-setup)" in err
    assert [*module.COMPOSE, "logs", "--no-color", "--tail", "20", "minio"] in asked


def fake_docker(tmp_path, log):
    """A docker on PATH that appends its arguments to `log` and succeeds. `docker ps` answers the folders in
    `stack-folders` (the working_dir label of each of the stack's containers), and fails while `ps-fails` exists."""
    tools = tmp_path / "fake-tools"
    tools.mkdir(exist_ok=True)
    docker = tools / "docker"
    docker.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n'
                      f'if [ "$1" = ps ]; then [ -f "{tmp_path}/ps-fails" ] && exit 1\n'
                      f'  [ -f "{tmp_path}/stack-folders" ] && cat "{tmp_path}/stack-folders"; fi\n'
                      'exit 0\n')
    docker.chmod(0o755)


def stack_runs_from(tmp_path, *folders):
    (tmp_path / "stack-folders").write_text("".join(f"{folder}\n" for folder in folders))


def compose_calls(log):
    return [line for line in log.read_text().splitlines() if line.startswith("compose ")] if log.exists() else []


def fake_path(tmp_path):
    return str(tmp_path / "fake-tools") + os.pathsep + os.environ["PATH"]


def test_stop_and_remove_act_on_this_install_only(tmp_path):
    d, log = install(tmp_path), tmp_path / "docker.log"
    fake_docker(tmp_path, log)
    run(d, "secrets")
    stack = "aisc-" + values(d / "env.secrets")["AISC_INSTALL"]
    stack_runs_from(tmp_path, d, d)
    assert run(d, "stop", path=fake_path(tmp_path)).returncode == 0
    stops = compose_calls(log)
    assert len(stops) == 1 and stops[0].startswith(f"compose -p {stack} ") and stops[0].endswith(" stop"), stops
    r = run(d, "remove", path=fake_path(tmp_path), stdin="wrong\n")
    assert r.returncode != 0 and "down" not in log.read_text()
    r = run(d, "remove", path=fake_path(tmp_path), stdin="")
    assert r.returncode != 0 and "down" not in log.read_text()
    r = run(d, "remove", path=fake_path(tmp_path), stdin=d.name + "\n")
    assert r.returncode == 0 and f"compose -p {stack}" in log.read_text() and "down -v" in log.read_text()
    assert all(line.split()[2] == stack for line in compose_calls(log))
    # each command first asked which folder the stack's containers belong to
    asked = [line for line in log.read_text().splitlines() if line.startswith("ps ")]
    assert asked and all(f"label=com.docker.compose.project={stack} " in line and "working_dir" in line
                         for line in asked), asked


def test_remove_refuses_where_nothing_was_installed(tmp_path):
    d, log = install(tmp_path), tmp_path / "docker.log"
    fake_docker(tmp_path, log)
    r = run(d, "remove", path=fake_path(tmp_path), stdin=d.name + "\n")
    assert r.returncode != 0 and not log.exists()
    r = run(d, "stop", path=fake_path(tmp_path))
    assert r.returncode != 0 and not log.exists()


# stop and remove act on a stack only when its containers were made from this folder: the stack's name alone can
# be another folder's (every install made before ids is aisc; AISC_PROJECT may be left in the shell)

def legacy_install(tmp_path):
    """A checkout whose env.secrets was made before ids: its stack is aisc."""
    d = install(tmp_path)
    run(d, "secrets")
    secrets = (d / "env.secrets").read_text().splitlines()
    (d / "env.secrets").write_text("\n".join(line for line in secrets if not line.startswith("AISC_INSTALL=")) + "\n")
    return d


@pytest.mark.parametrize("verb", ["stop", "remove"])
def test_a_stack_whose_containers_another_folder_made_is_neither_stopped_nor_removed(tmp_path, verb):
    d, log = legacy_install(tmp_path), tmp_path / "docker.log"
    fake_docker(tmp_path, log)
    elsewhere = tmp_path / "the-live-install"
    stack_runs_from(tmp_path, elsewhere, elsewhere)
    r = run(d, verb, path=fake_path(tmp_path), stdin=d.name + "\n")
    assert r.returncode != 0
    assert f"stack aisc belongs to {elsewhere}" in r.stderr and "run this there" in r.stderr
    assert not compose_calls(log), compose_calls(log)
    # refused before remove asks for the folder's name
    assert "Type the folder name" not in r.stdout


def test_a_stack_partly_made_from_another_folder_is_not_touched(tmp_path):
    d, log = legacy_install(tmp_path), tmp_path / "docker.log"
    fake_docker(tmp_path, log)
    stack_runs_from(tmp_path, d, tmp_path / "an-older-clone")
    r = run(d, "remove", path=fake_path(tmp_path), stdin=d.name + "\n")
    assert r.returncode != 0 and "an-older-clone" in r.stderr
    assert not compose_calls(log)


def test_an_install_made_before_ids_stops_and_removes_its_own_stack(tmp_path):
    d, log = legacy_install(tmp_path), tmp_path / "docker.log"
    fake_docker(tmp_path, log)
    stack_runs_from(tmp_path, d)
    assert run(d, "stop", path=fake_path(tmp_path)).returncode == 0
    r = run(d, "remove", path=fake_path(tmp_path), stdin=d.name + "\n")
    assert r.returncode == 0, r.stderr
    assert [c.split()[:3] for c in compose_calls(log)] == [["compose", "-p", "aisc"]] * 2
    assert compose_calls(log)[-1].endswith(" down -v --remove-orphans")


def test_the_folder_a_container_names_is_compared_resolved(tmp_path):
    d, log = install(tmp_path), tmp_path / "docker.log"
    fake_docker(tmp_path, log)
    run(d, "secrets")
    (tmp_path / "link-to-it").symlink_to(d, target_is_directory=True)
    stack_runs_from(tmp_path, tmp_path / "link-to-it")
    r = run(d, "stop", path=fake_path(tmp_path))
    assert r.returncode == 0, r.stderr
    assert compose_calls(log)


def test_remove_refuses_the_stack_aisc_when_no_container_shows_whose_it_is(tmp_path):
    """An older install's volumes can be left with no container: every checkout made before ids names the same
    stack aisc, so nothing proves they are this folder's."""
    d, log = legacy_install(tmp_path), tmp_path / "docker.log"
    fake_docker(tmp_path, log)
    r = run(d, "remove", path=fake_path(tmp_path), stdin=d.name + "\n")
    assert r.returncode != 0
    assert "aisc" in r.stderr and "docker volume ls --filter label=com.docker.compose.project=aisc" in r.stderr
    assert "nothing was removed" in r.stderr
    assert not compose_calls(log)


def test_remove_of_a_new_install_with_no_container_left_still_removes_its_own_data(tmp_path):
    """Its stack's name holds its own id, made with its env.secrets: the volumes are this folder's."""
    d, log = install(tmp_path), tmp_path / "docker.log"
    fake_docker(tmp_path, log)
    run(d, "secrets")
    stack = "aisc-" + values(d / "env.secrets")["AISC_INSTALL"]
    r = run(d, "remove", path=fake_path(tmp_path), stdin=d.name + "\n")
    assert r.returncode == 0, r.stderr
    assert [c.split()[2] for c in compose_calls(log)] == [stack]


@pytest.mark.parametrize("verb", ["stop", "remove"])
def test_aisc_project_naming_another_folder_s_stack_is_refused(tmp_path, verb):
    d, log = install(tmp_path), tmp_path / "docker.log"
    fake_docker(tmp_path, log)
    run(d, "secrets")
    stack_runs_from(tmp_path, tmp_path / "the-port-check-copy")
    r = run(d, verb, path=fake_path(tmp_path), stdin=d.name + "\n", AISC_PROJECT="aisc-ports")
    assert r.returncode != 0
    assert f"stack aisc-ports belongs to {tmp_path / 'the-port-check-copy'}" in r.stderr
    assert not compose_calls(log)


def test_remove_refuses_a_stack_named_from_the_shell_that_has_no_container(tmp_path):
    """AISC_PROJECT left in the shell names a stack this folder's id did not make: with no container to say
    whose it is, its volumes are not this folder's to delete."""
    d, log = install(tmp_path), tmp_path / "docker.log"
    fake_docker(tmp_path, log)
    run(d, "secrets")
    r = run(d, "remove", path=fake_path(tmp_path), stdin=d.name + "\n", AISC_PROJECT="aisc-ports")
    assert r.returncode != 0 and "nothing was removed" in r.stderr
    assert not compose_calls(log)


@pytest.mark.parametrize("verb", ["stop", "remove"])
def test_stop_and_remove_refuse_when_docker_cannot_list_the_stack(tmp_path, verb):
    d, log = install(tmp_path), tmp_path / "docker.log"
    fake_docker(tmp_path, log)
    run(d, "secrets")
    (tmp_path / "ps-fails").write_text("")
    r = run(d, verb, path=fake_path(tmp_path), stdin=d.name + "\n")
    assert r.returncode != 0
    assert not compose_calls(log)
