"""A run given a test database it cannot reach fails, instead of skipping every database test and passing:
scripts/test-platform.sh and CI then see a broken bed. A plain `pytest` with no database URL still skips them."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parent.parent
#: one module whose tests all need the database
SAMPLE = "tests/test_projectdb_connect.py"


def run(url: str | None):
    env = {k: v for k, v in os.environ.items() if k != "PLATFORM_TEST_DATABASE_URL"}
    if url is not None:
        env["PLATFORM_TEST_DATABASE_URL"] = url
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", SAMPLE],
                          cwd=PLATFORM_DIR, env=env, capture_output=True, text=True, timeout=300)


def test_an_unreachable_test_database_fails_the_run():
    done = run("postgresql://nobody:nothing@127.0.0.1:9/none")
    assert done.returncode != 0, done.stdout[-2000:]
    assert "cannot be reached" in done.stdout + done.stderr


def test_the_live_port_is_refused_loudly_too():
    done = run("postgresql://nobody:nothing@127.0.0.1:5432/platform")
    assert done.returncode != 0, done.stdout[-2000:]
    assert "5432" in done.stdout + done.stderr


def test_without_a_test_database_the_database_tests_skip():
    done = run(None)
    assert done.returncode == 0, done.stdout[-2000:]
    assert "skipped" in done.stdout and "failed" not in done.stdout
