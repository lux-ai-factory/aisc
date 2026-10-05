"""verify.sh --modules runs each module's suite the way the module expects to be run. Control objectives
refuses to run its database tests without a throwaway Postgres (it fails rather than skip, so a missing
database is never a pass): verify.sh gives it one, through scripts/lib/co-tests.sh."""
import subprocess

from conftest import ROOT

WRAPPER = ROOT / "scripts/lib/co-tests.sh"


def test_control_objectives_is_run_with_a_throwaway_database():
    line = next(l for l in (ROOT / "scripts/verify.sh").read_text().splitlines() if l.startswith("control objectives|"))
    assert "co-tests.sh" in line


def test_the_wrapper_uses_the_throwaway_helper_and_never_the_live_port():
    text = WRAPPER.read_text()
    assert ". " in text and "throwaway-pg.sh" in text and "tpg_start" in text
    assert "CONTROL_OBJECTIVES_TEST_DATABASE_URL" in text and "5432" not in text.replace("refuses 5432", "")
    assert subprocess.run(["bash", "-n", str(WRAPPER)]).returncode == 0


def test_the_engine_suite_runs_on_the_host_never_in_the_running_container():
    """Its tests find the repository from the backend's place in the checkout (apps/backend), and a test
    run has no business inside the live stack's container: the suite runs from the backend's own
    environment (uv sync), on SQLite, with the shared plugin libraries on the path."""
    line = next(l for l in (ROOT / "scripts/verify.sh").read_text().splitlines() if l.startswith("engine backend|"))
    name, directory, marker, command = line.split("|", 3)
    assert (directory, marker) == ("apps/backend", ".venv")
    assert "docker exec" not in command and "sqlite3" in command and "plugin-interface" in command
    for module in command.split("manage.py test", 1)[1].split():
        path = ROOT / directory / module.replace(".", "/")
        assert path.is_dir() or path.with_suffix(".py").exists(), f"no test module {module}"
