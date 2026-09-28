"""Tests of the pipeline's test infrastructure (pipeline 2026-09-23, 03 WP0, WP4, WP6a, WP12).

Run from the repo root:

    uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests

They start throwaway postgres:15-alpine containers (never the host's 5432) through
scripts/guard-frozen.sh and scripts/test-pipeline-chain.sh, and read `docker compose config`
of scratch copies of the compose files (never up, down or build).
"""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts/guard-frozen.sh"
CHAIN = ROOT / "scripts/test-pipeline-chain.sh"


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)


def container_name(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("container: "):
            return line.split(": ", 1)[1].strip()
    raise AssertionError("the script did not print its container name:\n" + output[-2000:])


def container_exists(name: str) -> bool:
    r = run(["docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"])
    return name in r.stdout.split()


@pytest.fixture(scope="session")
def guard_all(tmp_path_factory):
    """One full guard run (G1..G5), shared by the tests that read its verdict lines."""
    out = tmp_path_factory.mktemp("guard-all")
    r = run([str(GUARD)], env={**__import__("os").environ, "GUARD_OUT": str(out)}, timeout=900)
    return r, out


@pytest.fixture(scope="session")
def guard_orders(tmp_path_factory):
    out = tmp_path_factory.mktemp("guard-orders")
    r = run([str(GUARD), "--orders"], env={**__import__("os").environ, "GUARD_OUT": str(out)}, timeout=1800)
    return r, out


def verdict(output: str, check: str) -> list[str]:
    return [l for l in output.splitlines() if l.startswith(check + " ")]
