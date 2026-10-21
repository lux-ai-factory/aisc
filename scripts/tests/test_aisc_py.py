"""scripts/aisc.py run as the README runs it, `uv run scripts/aisc.py ...`, with no bash and no Unix tools. These
run on Linux and on CI's Windows runner, so what the script does with paths, files and line endings is checked on
both. uv brings the script's own Python and library, whatever the tests run on.

    uv run --no-project --with pytest python -m pytest -q scripts/tests/test_aisc_py.py
"""
import os
import shutil
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
