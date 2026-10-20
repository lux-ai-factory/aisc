"""The platform's tests never reach the live database (port 5432 of the running stack).

They use PLATFORM_TEST_DATABASE_URL only: not PLATFORM_DATABASE_URL (the stack's own, often set in a
shell that runs the stack), and no default. A test URL on port 5432 is refused. With none, the database
tests skip."""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _dsn_with(env: dict) -> str:
    code = ("import importlib.util, sys; spec = importlib.util.spec_from_file_location('c', sys.argv[1]);"
            " m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print(repr(m.DSN))")
    out = subprocess.run([sys.executable, "-c", code, str(HERE / "conftest.py")], capture_output=True, text=True,
                         env={"PATH": "/usr/bin:/bin", **env})
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_the_stacks_own_database_url_is_never_used():
    assert _dsn_with({"PLATFORM_DATABASE_URL": "postgresql://platform_rw:x@127.0.0.1:5432/platform"}) == "''"


def test_there_is_no_default():
    assert _dsn_with({}) == "''"


def test_a_test_url_on_the_live_port_is_refused():
    assert _dsn_with({"PLATFORM_TEST_DATABASE_URL": "postgresql://platform_rw:x@127.0.0.1:5432/platform"}) == "''"


def test_a_throwaway_test_url_is_used():
    url = "postgresql://platform_rw:x@127.0.0.1:55001/platform"
    assert _dsn_with({"PLATFORM_TEST_DATABASE_URL": url}) == repr(url)
