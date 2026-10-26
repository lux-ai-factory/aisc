"""The pipeline chain: scripts/test-pipeline-chain.sh."""

import os
import shutil
import subprocess

import pytest

from conftest import CHAIN, ROOT, container_exists, container_name, run

LINKS = ["qualification_fk", "co_fk", "engine_stamp", "controls_stamp", "card_component"]


@pytest.fixture(scope="module")
def full_run(tmp_path_factory):
    d = tmp_path_factory.mktemp("chain")
    return run([str(CHAIN)], env={**os.environ, "CHAIN_SCRATCH": str(d)}, timeout=3600)


def test_the_full_chain_passes(full_run):
    """Every step passes; step 8 reads v1 for the test result and v2 for the answer."""
    r = full_run
    assert r.returncode == 0 and "CHAIN PASS" in r.stdout, r.stdout[-3000:]
    assert "step 8 PASS" in r.stdout


@pytest.mark.parametrize("link", LINKS)
def test_each_break_fails_at_the_step_that_consumes_it(link, tmp_path):
    """`--break <link>` makes the run fail at the step that consumes the link, and not before."""
    r = run([str(CHAIN), "--break", link], env={**os.environ, "CHAIN_SCRATCH": str(tmp_path)}, timeout=3600)
    assert r.returncode == 0 and f"BREAK {link} OK" in r.stdout, r.stdout[-3000:]
    assert not container_exists(container_name(r.stdout))


def test_no_container_remains(full_run):
    """The chain's container is gone afterwards."""
    assert not container_exists(container_name(full_run.stdout))


def test_unknown_link_is_refused():
    """--break accepts only the five links in LINKS."""
    r = run([str(CHAIN), "--break", "nonsense"])
    assert r.returncode == 2


@pytest.fixture(scope="module")
def unprepared_root(tmp_path_factory):
    """A scratch root holding a copy of scripts/ only: no module is checked out."""
    d = tmp_path_factory.mktemp("unprepared")
    shutil.copytree(ROOT / "scripts", d / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    return d


def _chain_containers() -> set[str]:
    r = run(["docker", "ps", "-a", "--filter", "name=^aisc-t-chain-", "--format", "{{.Names}}"])
    return set(r.stdout.split())


def test_the_chain_refuses_to_start_without_the_module_environments(unprepared_root, tmp_path):
    """No container is started when scripts/prepare-tests.sh --check fails; its lines are printed."""
    before = _chain_containers()
    r = subprocess.run([str(unprepared_root / "scripts/test-pipeline-chain.sh")], cwd=unprepared_root,
                       env={**os.environ, "CHAIN_SCRATCH": str(tmp_path)}, capture_output=True, text=True,
                       timeout=600)
    assert r.returncode == 1, r.stdout[-3000:] + r.stderr[-2000:]
    assert ("chain: apps/qualification is not checked out: git submodule update --init apps/qualification"
            in r.stdout), r.stdout[-3000:]
    assert r.stdout.rstrip("\n").splitlines()[-1] == "CHAIN FAIL before step 1 (module environments missing)"
    assert not [line for line in r.stdout.splitlines() if line.startswith("container: ")]
    assert _chain_containers() == before


def test_an_unknown_link_is_refused_before_the_environment_check(unprepared_root):
    r = subprocess.run([str(unprepared_root / "scripts/test-pipeline-chain.sh"), "--break", "nonsense"],
                       cwd=unprepared_root, capture_output=True, text=True, timeout=120)
    assert r.returncode == 2, r.stdout[-2000:] + r.stderr[-2000:]
