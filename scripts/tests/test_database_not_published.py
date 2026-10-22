"""The checks that read the stack's Postgres from the host (verify-project-databases.sh, verify-db-consistency.sh)
connect to 127.0.0.1:5432, which a default install no longer publishes. Where nothing answers there, each says
how to publish it and fails, instead of failing on a connection error that does not say why."""
import os
import socket
import subprocess

import pytest

from conftest import ROOT

ADVICE = ("the database is not published on this machine: set AISC_ADMIN_PORTS=on (in the environment or "
          "env.local) and run start, then run this again")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.parametrize("script", ["scripts/verify-project-databases.sh", "scripts/verify-db-consistency.sh"])
def test_a_check_says_how_to_publish_the_database_when_nothing_answers(script, tmp_path):
    # PGPASSWORD set: the container is not asked for it; uv and docker fail if they are run at all
    shims = tmp_path / "shims"
    shims.mkdir()
    for name in ("uv", "docker"):
        (shims / name).write_text(f"#!/bin/sh\necho {name} was run >&2\nexit 99\n")
        (shims / name).chmod(0o755)
    env = {**os.environ, "PATH": f"{shims}:{os.environ['PATH']}", "PGHOST": "127.0.0.1", "PGPORT": str(free_port()),
           "PGPASSWORD": "not-used"}
    r = subprocess.run(["bash", str(ROOT / script)], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 1, r.stdout + r.stderr
    assert ADVICE in r.stderr
    assert "was run" not in r.stderr


def test_the_guide_says_the_stack_checks_need_the_database_published():
    guide = (ROOT / "docs/guide.md").read_text()
    stack = guide[guide.index("`./scripts/verify.sh --stack` runs"):][:1500]
    assert "AISC_ADMIN_PORTS=on" in stack
