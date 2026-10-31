"""scripts/report-grants.sh when Postgres answers pg_isready but cannot list the project databases.

The one-shot is the backstop that repairs the readers' grants in every project database. A listing
that fails must stop it with a failure, not let it print "done" having repaired nothing. Hermetic:
psql and pg_isready are stand-ins on PATH, no server is involved.
"""
import os
import subprocess

from conftest import ROOT

SCRIPT = ROOT / "scripts/report-grants.sh"


def fake_tools(tmp_path, listing: str) -> dict:
    """psql that runs the SQL files and blocks, and answers the database listing with `listing`
    ("fail", or the names to print); pg_isready that says ready."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "pg_isready").write_text("#!/bin/sh\nexit 0\n")
    log = tmp_path / "psql.log"
    (bin_dir / "psql").write_text(f"""#!/bin/sh
for a in "$@"; do
  case "$a" in
    *pg_database*)
      if [ "{listing}" = fail ]; then echo 'psql: error: permission denied' >&2; exit 2; fi
      printf '%s\\n' {listing}; exit 0;;
  esac
done
cat >/dev/null
echo "$*" >> "{log}"
exit 0
""")
    for tool in bin_dir.iterdir():
        tool.chmod(0o755)
    return {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}


def run(env):
    return subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30)


def test_a_listing_that_fails_stops_the_one_shot_with_a_failure(tmp_path):
    result = run(fake_tools(tmp_path, "fail"))
    assert result.returncode != 0
    assert "[report-grants] done" not in result.stdout
    assert "project databases" in result.stderr


def test_each_listed_database_is_granted_and_the_run_ends_done(tmp_path):
    names = "project_" + "a" * 32 + " project_" + "b" * 32
    result = run(fake_tools(tmp_path, names))
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-3:] == ["[report-grants] project_" + "a" * 32,
                                               "[report-grants] project_" + "b" * 32, "[report-grants] done"]


def test_no_project_database_yet_is_done(tmp_path):
    result = run(fake_tools(tmp_path, "''"))
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == "[report-grants] done"
