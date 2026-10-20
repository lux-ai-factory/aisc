"""scripts/verify-db-access.sh cleans up only the probe project it made.

Section 1 inserts one core.project row with slug `probe-<pid>`; the cleanup deleted every row whose
slug is like 'probe-%', so a real project named "Probe 1" (slug probe-1) was deleted, as the
superuser, on the running stack, with the output discarded.

The script runs with a fake `docker` on PATH that records every SQL statement it is given (`-c`);
nothing reaches a database."""
import os
import re
import subprocess

from conftest import ROOT

SCRIPT = ROOT / "scripts/verify-db-access.sh"

FAKE_DOCKER = """#!/usr/bin/env bash
next=0
for a in "$@"; do
  if [ "$next" = 1 ]; then printf '%s\\n\\x1e\\n' "$a" >> "$SQL"; next=0; fi
  [ "$a" = "-c" ] && next=1
done
exit 0
"""


def statements(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(FAKE_DOCKER)
    (bin_dir / "docker").chmod(0o755)
    log = tmp_path / "sql"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "SQL": str(log)}
    subprocess.run(["bash", str(SCRIPT)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    return [s.strip() for s in log.read_text().split("\x1e") if s.strip()]


def test_the_cleanup_deletes_exactly_the_probe_project_it_made(tmp_path):
    sql = statements(tmp_path)
    made = [re.search(r"'(probe-\d+)'\)", s).group(1) for s in sql
            if s.startswith("insert into core.project") and "'probe'" in s]
    assert len(made) == 1, made
    deletes = [s for s in sql if re.search(r"delete\s+from\s+core\.project\b(?!_)", s)]
    assert deletes, "the probe project is not cleaned up"
    for s in deletes:
        assert " like " not in s.lower(), f"a pattern delete: {s}"
        assert re.search(rf"slug\s*=\s*'{made[0]}'", s), f"does not name the probe's own slug: {s}"
