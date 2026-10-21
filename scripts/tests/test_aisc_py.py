"""scripts/aisc.py run as the README runs it, `uv run scripts/aisc.py ...`, with no bash and no Unix tools. These
run on Linux and on CI's Windows runner, so what the script does with paths, files and line endings is checked on
both. uv brings the script's own Python and library, whatever the tests run on.

    uv run --no-project --with pytest python -m pytest -q scripts/tests/test_aisc_py.py
"""
import os
import shutil
import socket
import subprocess

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
    assert m.engine_settings(80, 443)["API_URL_EXTERNAL"] == "http://localhost"
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


def test_the_runtime_env_takes_the_install_settings_last(tmp_path):
    """env.local holds what start chose for this install; the by-hand path (secrets, then compose) keeps it."""
    d = install(tmp_path)
    assert run(d, "secrets").returncode == 0
    (d / "env.local").write_text("API_URL_EXTERNAL=http://localhost:8080\nENGINE_PORT=8080\n")
    r = run(d, "secrets")
    assert r.returncode == 0, r.stderr
    lines = (d / "env.runtime").read_text().splitlines()
    assert lines[-2:] == ["API_URL_EXTERNAL=http://localhost:8080", "ENGINE_PORT=8080"]
