"""scripts/lib/controls-tests.sh: the controls app's integration tests on a throwaway Postgres, all of them or the
files given.

Checked with stand-ins for `docker` and `npx` first on PATH: docker answers every call (the throwaway database
"comes up" at once) and npx records its arguments, its folder and the database address it got. Nothing is
started and no database is used.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from conftest import ROOT

SCRIPT = ROOT / "scripts/lib/controls-tests.sh"
CONTROLS = ROOT / "apps/controls"

STAND_IN_DOCKER = """#!/usr/bin/env bash
# reads what psql would have read, so the caller's pipe is drained
for arg in "$@"; do [ "$arg" = "-i" ] && cat >/dev/null; done
exit 0
"""

STAND_IN_NPX = r"""#!/usr/bin/env bash
python3 - "$@" <<'PY'
import json, os, sys
with open(os.environ["STAND_IN_LOG"], "w") as f:
    json.dump({"argv": sys.argv[1:], "cwd": os.getcwd(),
               "database": os.environ.get("PROJECT_DATABASE_URL", "")}, f)
PY
"""


def run(tmp_path: Path, *args: str):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, text in (("docker", STAND_IN_DOCKER), ("npx", STAND_IN_NPX)):
        (bin_dir / name).write_text(text)
        (bin_dir / name).chmod(0o755)
    log = tmp_path / "npx-call.json"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "STAND_IN_LOG": str(log)}
    r = subprocess.run(["bash", str(SCRIPT), *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    return r, json.loads(log.read_text()) if log.is_file() else None


def test_without_files_it_runs_the_whole_integration_folder(tmp_path):
    r, call = run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert call["argv"] == ["vitest", "run", "test/integration"]
    assert Path(call["cwd"]).resolve() == CONTROLS.resolve()
    assert ":5432/" not in call["database"]


def test_files_given_narrow_the_run_to_them(tmp_path):
    r, call = run(tmp_path, "test/integration/races.test.ts", "test/integration/install.test.ts")
    assert r.returncode == 0, r.stderr
    assert call["argv"] == ["vitest", "run", "test/integration/races.test.ts", "test/integration/install.test.ts"]


def test_a_file_named_from_the_repository_root_is_found_in_the_app(tmp_path):
    r, call = run(tmp_path, "apps/controls/test/integration/races.test.ts")
    assert r.returncode == 0, r.stderr
    assert call["argv"] == ["vitest", "run", "test/integration/races.test.ts"]


def test_options_alone_keep_the_whole_folder_and_reach_vitest(tmp_path):
    r, call = run(tmp_path, "--reporter", "verbose")
    assert r.returncode == 0, r.stderr
    assert call["argv"] == ["vitest", "run", "test/integration", "--reporter", "verbose"]


def test_a_file_that_does_not_exist_is_refused(tmp_path):
    r, call = run(tmp_path, "test/integration/no-such.test.ts")
    assert r.returncode == 2 and call is None
    assert "no-such.test.ts" in r.stderr
