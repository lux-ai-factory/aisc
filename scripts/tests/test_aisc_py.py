"""scripts/aisc.py run as the README runs it, `uv run scripts/aisc.py ...`, with no bash and no Unix tools. These
run on Linux and on CI's Windows runner, so what the script does with paths, files and line endings is checked on
both. uv brings the script's own Python and library, whatever the tests run on.

    uv run --no-project --with pytest python -m pytest -q scripts/tests/test_aisc_py.py
"""
import os
import shutil
import socket
import subprocess

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
    return dict(l.split("=", 1) for l in path.read_text().splitlines() if "=" in l and not l.startswith("#"))


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


# The ports: a taken one is tested before anything is built, and a new install moves off a taken 80 or 443

def test_a_taken_port_falls_back_to_the_first_free_one():
    m = aisc_py()
    assert m.choose_port(80, (8080, 8090), lambda p: p == 8090) == 8090
    assert m.choose_port(80, (8080, 8090), lambda p: True) == 80
    assert m.choose_port(80, (8080, 8090), lambda p: False) is None


def test_the_engine_address_drops_the_default_port():
    """Browsers send the Origin of http://localhost:80 as http://localhost: the address must match it."""
    m = aisc_py()
    assert m.engine_settings(8080, 8443) == {"ENGINE_PORT": "8080", "ENGINE_HTTPS_PORT": "8443",
                                             "API_URL_EXTERNAL": "http://localhost:8080"}


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


#: what docker compose config publishes, in settle_ports' terms: (address, published port, container port)
PUBLISHED = [("0.0.0.0", 80, 8005), ("0.0.0.0", 443, 8005), ("0.0.0.0", 8100, 8006), ("127.0.0.1", 5432, 5432)]
FALLBACKS_OF_80 = (8080, 8090, 8000, 8880, 8888)


def taken(*ports):
    return lambda port, host: port not in ports


def test_a_new_install_moves_off_a_taken_port_80():
    settings, problems = aisc_py().settle_ports(PUBLISHED, set(), {}, True, taken(80))
    assert problems == []
    assert settings == {"ENGINE_PORT": "8080", "ENGINE_HTTPS_PORT": "443", "API_URL_EXTERNAL": "http://localhost:8080"}


def test_with_every_port_free_nothing_changes():
    settings, problems = aisc_py().settle_ports(PUBLISHED, set(), {}, True, taken())
    assert problems == []
    assert settings == {"ENGINE_PORT": "80", "ENGINE_HTTPS_PORT": "443"}


def test_ports_held_by_aisc_itself_are_not_taken():
    """A second start finds its own stack on its ports: that is not a reason to move."""
    settings, problems = aisc_py().settle_ports(PUBLISHED, {80, 443, 8100, 5432}, {}, False, taken(80, 443, 8100, 5432))
    assert problems == []
    assert settings["ENGINE_PORT"] == "80"


def test_an_install_with_data_never_moves():
    """Its sign-in was set up for the address it has; moving would lock its users out."""
    m = aisc_py()
    settings, problems = m.settle_ports(PUBLISHED, set(), {}, False, taken(80))
    assert len(problems) == 1 and "80" in problems[0] and m.who_holds(80) in problems[0]


def test_kept_ports_are_reused():
    kept = {"ENGINE_PORT": "8090", "ENGINE_HTTPS_PORT": "443", "API_URL_EXTERNAL": "http://localhost:8090"}
    settings, problems = aisc_py().settle_ports(PUBLISHED, set(), kept, False, taken())
    assert problems == [] and settings["ENGINE_PORT"] == "8090"
    assert settings["API_URL_EXTERNAL"] == "http://localhost:8090"


def test_a_kept_port_taken_later_stops_start():
    kept = {"ENGINE_PORT": "8090", "ENGINE_HTTPS_PORT": "443", "API_URL_EXTERNAL": "http://localhost:8090"}
    settings, problems = aisc_py().settle_ports(PUBLISHED, set(), kept, False, taken(8090))
    assert len(problems) == 1 and "8090" in problems[0]


def test_every_fallback_taken_stops_start():
    settings, problems = aisc_py().settle_ports(PUBLISHED, set(), {}, True, taken(80, *FALLBACKS_OF_80))
    assert len(problems) == 1
    assert all(str(p) in problems[0] for p in (80, *FALLBACKS_OF_80))


def test_other_taken_ports_are_named_with_their_holder_command():
    m = aisc_py()
    settings, problems = m.settle_ports(PUBLISHED, set(), {}, True, taken(5432))
    assert len(problems) == 1 and "5432" in problems[0] and m.who_holds(5432) in problems[0]


def test_published_ports_reads_compose_config():
    config = {"services": {"caddy": {"ports": [{"published": "80", "target": 8005}]},
                           "postgres": {"ports": [{"host_ip": "127.0.0.1", "published": "5432", "target": 5432}]},
                           "platform": {}}}
    assert aisc_py().published_ports(config) == [("0.0.0.0", 80, 8005), ("127.0.0.1", 5432, 5432)]


def test_the_project_name_can_be_set(monkeypatch):
    """A second copy beside an existing install's data runs under its own name."""
    assert aisc_py().COMPOSE[:4] == ["docker", "compose", "-p", "aisc"]
    monkeypatch.setenv("AISC_PROJECT", "aisc-proof")
    assert aisc_py().COMPOSE[:4] == ["docker", "compose", "-p", "aisc-proof"]


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


def test_an_engine_on_port_80_leaves_the_install_its_own_address():
    """https and custom-host installs set API_URL_EXTERNAL themselves; only a moved engine overrides it."""
    assert aisc_py().engine_settings(80, 443) == {"ENGINE_PORT": "80", "ENGINE_HTTPS_PORT": "443"}


def test_a_reserved_port_on_windows_is_taken(monkeypatch):
    """Windows refuses a bind on its reserved ranges (Hyper-V, WSL) with an access error: Docker cannot use
    the port either, whatever answers a connect."""
    m = aisc_py()

    def refused(self, address):
        raise PermissionError(10013, "access forbidden")

    monkeypatch.setattr(socket.socket, "bind", refused)
    monkeypatch.setattr(m.os, "name", "nt")
    assert not m.port_is_free(51234, "0.0.0.0")


def test_a_kept_port_on_an_install_without_data_may_still_move():
    """No sign-in was set up yet (the first start stopped before up), so moving is safe."""
    kept = {"ENGINE_PORT": "80", "ENGINE_HTTPS_PORT": "443"}
    settings, problems = aisc_py().settle_ports(PUBLISHED, set(), kept, True, taken(80))
    assert problems == [] and settings["ENGINE_PORT"] == "8080"
