"""verify.sh --modules runs each module's suite the way the module expects to be run: the rows of
scripts/suites.py. Control objectives refuses to run its database tests without a throwaway Postgres (it fails
rather than skip, so a missing database is never a pass): its row runs scripts/lib/co-tests.sh."""
import subprocess
import sys

from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import suites  # noqa: E402

WRAPPER = ROOT / "scripts/lib/co-tests.sh"


def row(name: str) -> suites.Suite:
    return next(s for s in suites.SUITES if s.name == name)


def test_control_objectives_is_run_with_a_throwaway_database():
    assert "co-tests.sh" in row("control-objectives").command


def test_the_wrapper_uses_the_throwaway_helper_and_never_the_live_port():
    text = WRAPPER.read_text()
    assert ". " in text and "throwaway-pg.sh" in text and "tpg_start" in text
    assert "CONTROL_OBJECTIVES_TEST_DATABASE_URL" in text and "5432" not in text.replace("refuses 5432", "")
    assert subprocess.run(["bash", "-n", str(WRAPPER)]).returncode == 0


def test_the_engine_suite_runs_on_the_host_never_in_the_running_container():
    """Its tests find the repository from the backend's place in the checkout (apps/backend), and a test
    run has no business inside the live stack's container: both engine rows run scripts/lib/engine-tests.sh,
    from the engine's lock with the vendored wheels, on SQLite or on a throwaway Postgres."""
    for name in ("engine", "engine on postgres"):
        s = row(name)
        assert s.dir == "apps/backend" and "docker exec" not in s.command
        assert s.command.split()[0] == "scripts/lib/engine-tests.sh"


def test_the_platform_suite_runs_with_a_throwaway_database():
    """Without PLATFORM_TEST_DATABASE_URL the platform's database tests skip, and a skip is not a pass."""
    assert "test-platform.sh" in row("platform").command


def test_verify_runs_the_renderers_and_the_agents():
    names = {s.name for s in suites.SUITES}
    assert {"qualification pdf", "qualification agents", "controls pdf"} <= names


def test_a_row_reads_no_more_stdin_than_its_own():
    """The rows reach the loop on its stdin: a command that read stdin would swallow the rows after it."""
    assert 'run "$name" bash -c "$cmd" </dev/null' in (ROOT / "scripts/verify.sh").read_text()
