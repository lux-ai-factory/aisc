"""The pipeline chain: scripts/test-pipeline-chain.sh."""

import os

import pytest

from conftest import CHAIN, container_exists, container_name, run

LINKS = ["qualification_fk", "co_fk", "engine_stamp", "controls_stamp", "card_component"]


@pytest.fixture(scope="module")
def full_run(tmp_path_factory):
    d = tmp_path_factory.mktemp("chain")
    return run([str(CHAIN)], env={**os.environ, "CHAIN_SCRATCH": str(d)}, timeout=3600)


def test_s12_1_the_full_chain_passes(full_run):
    """Every step passes; step 8 reads v1 for the test result and v2 for the answer."""
    r = full_run
    assert r.returncode == 0 and "CHAIN PASS" in r.stdout, r.stdout[-3000:]
    assert "step 8 PASS" in r.stdout


@pytest.mark.parametrize("link", LINKS)
def test_s12_2_each_break_fails_at_the_step_that_consumes_it(link, tmp_path):
    """`--break <link>` makes the run fail at the step that consumes the link, and not before."""
    r = run([str(CHAIN), "--break", link], env={**os.environ, "CHAIN_SCRATCH": str(tmp_path)}, timeout=3600)
    assert r.returncode == 0 and f"BREAK {link} OK" in r.stdout, r.stdout[-3000:]
    assert not container_exists(container_name(r.stdout))


def test_s12_3_no_container_remains(full_run):
    """The chain's container is gone afterwards."""
    assert not container_exists(container_name(full_run.stdout))


def test_s12_unknown_link_is_refused():
    """--break accepts only the five links in LINKS."""
    r = run([str(CHAIN), "--break", "nonsense"])
    assert r.returncode == 2
