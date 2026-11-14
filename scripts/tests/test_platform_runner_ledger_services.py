"""scripts/test-platform.sh runs the immudb tests on a throwaway immudb and fails on a skip nobody allowed.

Read-only: the runner and the throwaway helper are read as text, nothing is started.
"""

from __future__ import annotations

from conftest import ROOT

RUNNER = ROOT / "scripts/test-platform.sh"
HELPER = ROOT / "scripts/lib/throwaway-immudb.sh"


def test_there_is_a_throwaway_immudb_helper_on_a_pinned_image_without_a_volume():
    assert HELPER.is_file(), "scripts/lib/throwaway-immudb.sh does not exist"
    text = HELPER.read_text()
    assert "codenotary/immudb:1.11.1" in text
    for name in ("timmu_start", "timmu_cleanup", "TIMMU_URL", "TIMMU_ADMIN_PASSWORD"):
        assert name in text, name
    assert "-v " not in text and "--volume" not in text, "a throwaway immudb keeps no volume"
    assert "3322" in text, "the helper must refuse the stack's immudb port"


def test_the_platform_runner_starts_an_immudb_and_requires_the_ledger_services():
    text = RUNNER.read_text()
    assert "throwaway-immudb.sh" in text and "timmu_start" in text and "timmu_cleanup" in text
    for name in ("LEDGER_TEST_IMMUDB_URL", "LEDGER_TEST_IMMUDB_ADMIN_PASSWORD", "LEDGER_TESTS_REQUIRED=1",
                 "PLATFORM_TESTS_STRICT_SKIPS=1", "-p tests.skip_guard"):
        assert name in text, name


def test_every_trap_of_the_platform_runner_removes_the_throwaway_immudb():
    traps = [line for line in RUNNER.read_text().splitlines() if line.startswith("trap ")]
    assert len(traps) == 3, traps
    assert all("timmu_cleanup" in line for line in traps), traps
