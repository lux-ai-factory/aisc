"""The platform suite fails a run that skips a test for a reason nobody allowed.

A skip hides a test that never ran. Only three reasons are allowed: the opt-in drills, the pipeline chain
outside its own run, and the adapters end-to-end test without a real adapters folder. Any other skip (a
missing throwaway immudb, MinIO or database) fails the run when PLATFORM_TESTS_STRICT_SKIPS=1, which is how
scripts/test-platform.sh runs the suite.

    bash scripts/test-platform.sh -q tests/test_skip_guard.py
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parents[1]
ALLOWED = ("drills are opt-in: LEDGER_DRILLS=1", "not in the pipeline chain (CHAIN_JSON unset)",
           "AISC_ADAPTER_E2E_DIR names a real adapters folder")


def _guard():
    assert importlib.util.find_spec("tests.skip_guard") is not None, \
        "there is no skip guard plugin (tests/skip_guard.py)"
    return importlib.import_module("tests.skip_guard")


def test_the_allowed_skips_are_the_opt_in_drills_the_chain_and_the_adapter_end_to_end():
    assert _guard().ALLOWED_SKIPS == ALLOWED


def test_only_unlisted_reasons_are_unexpected():
    unexpected = _guard().unexpected_skips(["drills are opt-in: LEDGER_DRILLS=1",
                                            "LEDGER_TEST_IMMUDB_URL / ... are not set"])
    assert unexpected == ["LEDGER_TEST_IMMUDB_URL / ... are not set"]


def _run_one(tmp_path, reason):
    test = tmp_path / "test_one.py"
    test.write_text(f"import pytest\n\n\ndef test_it():\n    pytest.skip({reason!r})\n")
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "tests.skip_guard", "-p", "no:cacheprovider",
                           "--rootdir", str(tmp_path), str(test)],
                          cwd=PLATFORM_DIR, capture_output=True, text=True, timeout=120,
                          env={**os.environ, "PLATFORM_TESTS_STRICT_SKIPS": "1"})


def test_an_unlisted_skip_fails_the_run(tmp_path):
    r = _run_one(tmp_path, "no throwaway MinIO")
    out = r.stdout + r.stderr
    assert r.returncode != 0, "a skip nobody allowed passed the run"
    assert "skip not allowed: no throwaway MinIO" in out, out[-1500:]


def test_an_allowed_skip_passes_the_run(tmp_path):
    r = _run_one(tmp_path, "drills are opt-in: LEDGER_DRILLS=1")
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
