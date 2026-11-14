"""A pytest plugin that fails the run on a skip nobody allowed.

A skipped test is a test that never ran. scripts/test-platform.sh starts every service the suite needs
(PostgreSQL, MinIO, immudb), so the only skips left should be the ones that are opt-in by design:

- the ledger drills (LEDGER_DRILLS=1),
- the pipeline chain test outside the chain's own run (CHAIN_JSON),
- the adapters end-to-end test without a real adapters folder (AISC_ADAPTER_E2E_DIR).

Loaded with `-p tests.skip_guard`. It only acts when PLATFORM_TESTS_STRICT_SKIPS=1: then each other skip
reason is printed as `skip not allowed: <reason>` and the run exits non-zero. Adding a reason to
ALLOWED_SKIPS hides a test for good, so it needs the owner's yes.
"""

from __future__ import annotations

import os

import pytest

ALLOWED_SKIPS: tuple[str, ...] = (
    "drills are opt-in: LEDGER_DRILLS=1",
    "not in the pipeline chain (CHAIN_JSON unset)",
    "AISC_ADAPTER_E2E_DIR names a real adapters folder",
)

_SKIPPED_PREFIX = "Skipped: "
_reasons: list[str] = []


def unexpected_skips(reasons: list[str]) -> list[str]:
    """The reasons that are not in ALLOWED_SKIPS, in order, each once."""
    seen: list[str] = []
    for reason in reasons:
        if reason not in ALLOWED_SKIPS and reason not in seen:
            seen.append(reason)
    return seen


def _strict() -> bool:
    return os.environ.get("PLATFORM_TESTS_STRICT_SKIPS") == "1"


def _reason(report: pytest.TestReport) -> str:
    longrepr = report.longrepr
    message = longrepr[2] if isinstance(longrepr, tuple) and len(longrepr) == 3 else str(longrepr)
    return message.removeprefix(_SKIPPED_PREFIX)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.skipped and not hasattr(report, "wasxfail"):
        _reasons.append(_reason(report))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not _strict():
        return
    unexpected = unexpected_skips(_reasons)
    if not unexpected:
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    for reason in unexpected:
        line = f"skip not allowed: {reason}"
        if reporter is not None:
            reporter.write_line(line, red=True)
        else:
            print(line)
    if session.exitstatus == 0:
        session.exitstatus = 1
