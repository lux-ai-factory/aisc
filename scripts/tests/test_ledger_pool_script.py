"""scripts/ledger-pool.sh on a scratch copy, with a stand-in `docker` that records what it is asked to
run (phase 1 review M3). Nothing is started; no secret is printed.

The platform container has no ledger settings of its own, so the script must hand it the immudb URL
and the ledger user's password (from env.secrets) as well as the superuser's (from this shell), all as
`-e NAME` so no value is ever on a command line.
"""
import os
import shutil
import subprocess

import pytest

from conftest import ROOT

SECRET_PW = "f" * 64
SUPER_PW = "super-secret-0123456789"


@pytest.fixture
def scratch(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/ledger-pool.sh", tmp_path / "scripts/ledger-pool.sh")
    (tmp_path / "env.secrets").write_text(f"LEDGER_IMMUDB_PASSWORD={SECRET_PW}\nOTHER=x\n")
    (tmp_path / "env.runtime").write_text("")
    bin_dir = tmp_path / "shims"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" > {tmp_path}/argv\n"
        f"env > {tmp_path}/env\n")
    (bin_dir / "docker").chmod(0o755)
    return tmp_path


def run(d, *args, super_pw=SUPER_PW):
    env = {k: v for k, v in os.environ.items() if k not in ("IMMUDB_ADMIN_PASSWORD", "LEDGER_IMMUDB_PASSWORD")}
    env["PATH"] = f"{d}/shims:{env['PATH']}"
    if super_pw is not None:
        env["IMMUDB_ADMIN_PASSWORD"] = super_pw
    return subprocess.run(["bash", str(d / "scripts/ledger-pool.sh"), *args], cwd=d, env=env,
                          capture_output=True, text=True, timeout=60)


def test_the_container_gets_every_setting_it_needs_by_name_only(scratch):
    r = run(scratch, "5")
    assert r.returncode == 0, r.stderr
    argv = (scratch / "argv").read_text().split("\n")
    for name in ("IMMUDB_ADMIN_PASSWORD", "LEDGER_IMMUDB_PASSWORD", "LEDGER_IMMUDB_URL"):
        assert name in argv and argv[argv.index(name) - 1] == "-e", f"{name} is not passed as -e NAME"
    assert argv[argv.index("create") - 1] == "platform_service.ledger.pool" and argv[argv.index("create") + 1] == "5"
    joined = "\n".join(argv)
    assert SECRET_PW not in joined and SUPER_PW not in joined           # no value on the command line
    env = (scratch / "env").read_text()
    assert f"LEDGER_IMMUDB_PASSWORD={SECRET_PW}" in env and f"IMMUDB_ADMIN_PASSWORD={SUPER_PW}" in env
    assert "LEDGER_IMMUDB_URL=immudb:3322" in env
    assert SECRET_PW not in r.stdout + r.stderr and SUPER_PW not in r.stdout + r.stderr


def test_without_the_superuser_password_nothing_runs(scratch):
    r = run(scratch, super_pw=None)
    assert r.returncode != 0 and not (scratch / "argv").exists()


def test_without_the_ledger_users_password_nothing_runs(scratch):
    (scratch / "env.secrets").write_text("OTHER=x\n")
    r = run(scratch)
    assert r.returncode != 0 and "LEDGER_IMMUDB_PASSWORD" in r.stderr and not (scratch / "argv").exists()
