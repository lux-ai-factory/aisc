"""scripts/aisc.py run as the README runs it, `uv run scripts/aisc.py ...`, with no bash and no Unix tools. These
run on Linux and on CI's Windows runner, so what the script does with paths, files and line endings is checked on
both. uv brings the script's own Python and library, whatever the tests run on.

    uv run --no-project --with pytest python -m pytest -q scripts/tests/test_aisc_py.py
"""
import os
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


def run(d, *args, path=None):
    env = {**os.environ}
    env.pop("CADDY_DOMAIN", None)
    if path is not None:
        env["PATH"] = path
    return subprocess.run([UV, "run", "--quiet", "--script", str(d / "scripts/aisc.py"), *args], cwd=d, env=env,
                          capture_output=True, text=True, timeout=300)


def values(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line and not line.startswith("#"))


def test_secrets_makes_every_secret_the_runtime_env_and_the_signing_key(tmp_path):
    d = install(tmp_path)
    r = run(d, "secrets")
    assert r.returncode == 0, r.stderr
    made = values(d / "env.secrets")
    assert list(made) == [name for name, _ in aisc_py().SECRETS]
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
    assert lines[-2:] == ["API_URL_EXTERNAL=http://localhost:8080", "ENGINE_PORT=8080"]


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


def test_the_project_name_can_be_set(monkeypatch):
    """A second copy beside an existing install's data runs under its own name."""
    assert aisc_py().COMPOSE[:4] == ["docker", "compose", "-p", "aisc"]
    monkeypatch.setenv("AISC_PROJECT", "aisc-proof")
    assert aisc_py().COMPOSE[:4] == ["docker", "compose", "-p", "aisc-proof"]


def test_compose_adds_the_https_file_only_for_https(monkeypatch):
    """443 is published only by an install served over https: elsewhere a taken 443 must not stop a start."""
    monkeypatch.setenv("CADDY_DOMAIN", "http://localhost")
    assert "docker-compose.https.yml" not in aisc_py().COMPOSE
    assert "docker-compose.https.yml" not in aisc_py().UP_HINT
    monkeypatch.setenv("CADDY_DOMAIN", "https://x")
    module = aisc_py()
    assert module.COMPOSE[-2:] == ["-f", "docker-compose.https.yml"]
    assert "-f docker-compose.https.yml" in module.UP_HINT


def test_compose_adds_the_admin_ports_file_only_when_asked(monkeypatch):
    monkeypatch.setenv("CADDY_DOMAIN", "http://localhost")
    monkeypatch.delenv("AISC_ADMIN_PORTS", raising=False)
    assert "docker-compose.admin-ports.yml" not in aisc_py().COMPOSE
    monkeypatch.setenv("AISC_ADMIN_PORTS", "on")
    module = aisc_py()
    assert module.COMPOSE[-2:] == ["-f", "docker-compose.admin-ports.yml"]
    assert "-f docker-compose.admin-ports.yml" in module.UP_HINT


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
                                        "https://aisc.example.org:8188")
    gateway, webapp = clients["aisc-gateway"], clients["aisc-webapp"]
    assert gateway["redirectUris"] == ["https://aisc.example.org/oauth2/callback",
                                       "https://aisc.example.org:8100/oauth2/callback",
                                       "https://aisc.example.org:8188/oauth2/callback"]
    assert gateway["attributes"]["post.logout.redirect.uris"] == \
        "https://aisc.example.org:8100/*##https://aisc.example.org/*"
    assert webapp["baseUrl"] == "https://aisc.example.org"
    assert webapp["redirectUris"] == ["https://aisc.example.org/*", "http://localhost:5173/*"]
    assert webapp["webOrigins"] == ["https://aisc.example.org", "http://localhost:5173"]


def test_start_and_rotate_infra_password_sign_kcadm_in_the_same_way():
    """One login for every kcadm call: Keycloak's admin from its environment, a session file removed after."""
    m = aisc_py()
    login = m.KCADM_RUN.split("&&")[0]
    assert "$ADMIN_VALUE" in login and m.KCADM.split("&&")[0] == login
    assert m.KCADM_RUN.split("&&")[1].split(";")[1:] == m.KCADM.split("&&")[1].split(";")[1:]
