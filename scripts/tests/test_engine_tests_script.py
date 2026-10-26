"""scripts/lib/engine-tests.sh: the engine's tests in one command, the way CI runs them.

    scripts/lib/engine-tests.sh [manage.py test arguments]              # sqlite, default mode
    scripts/lib/engine-tests.sh --postgres [manage.py test arguments]   # throwaway Postgres, configurator mode

The sqlite mode's command line is checked with a stand-in `uv` first on PATH that records its arguments, its
folder and the environment it got, so these cases are fast and never run the engine. The real runs (both modes,
about four minutes with Docker) run with AISC_ENGINE_SCRIPT_CHECK=1:

    AISC_ENGINE_SCRIPT_CHECK=1 uv run --no-project --with pytest --with pyyaml \
        python -m pytest -q -p no:cacheprovider scripts/tests/test_engine_tests_script.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT

SCRIPT = ROOT / "scripts/lib/engine-tests.sh"
BACKEND = ROOT / "apps/backend"
TESTS = BACKEND / "aisc_backend/tests"
RUNNER = ["run", "--locked", "--all-extras", "python", "manage.py", "test"]

needs_backend = pytest.mark.skipif(not (TESTS / "__init__.py").is_file(), reason="apps/backend is not checked out")
real_runs = pytest.mark.skipif(os.environ.get("AISC_ENGINE_SCRIPT_CHECK") != "1",
                               reason="the engine's real runs: set AISC_ENGINE_SCRIPT_CHECK=1")
needs_docker = pytest.mark.skipif(shutil.which("docker") is None, reason="docker is not installed")

STAND_IN_UV = r"""#!/usr/bin/env bash
python3 - "$@" <<'PY'
import json, os, sys
db_name = os.environ.get("DB_NAME", "")
record = {
    "argv": sys.argv[1:],
    "cwd": os.getcwd(),
    "env": {k: os.environ[k] for k in ("DATABASE_URL", "DB_ENGINE", "DB_NAME", "PYTHONPATH", "AISC_DEPLOYMENT")
            if k in os.environ},
    "db_folder_existed": bool(db_name) and os.path.isdir(os.path.dirname(db_name)),
}
with open(os.environ["STAND_IN_LOG"], "w") as f:
    json.dump(record, f)
PY
exit "${STAND_IN_EXIT:-0}"
"""


def expected_labels() -> list[str]:
    """Every package folder directly under aisc_backend/tests with an __init__.py but `integration`, and every
    test_*.py module directly under it, as dotted labels, sorted."""
    packages = [p.name for p in TESTS.iterdir()
                if p.is_dir() and (p / "__init__.py").is_file() and p.name != "integration"]
    modules = [p.stem for p in TESTS.glob("test_*.py")]
    return sorted(f"aisc_backend.tests.{name}" for name in packages + modules)


def run_with_stand_in(tmp_path: Path, *args: str, cwd: Path = ROOT, exit_code: int = 0):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    uv = bin_dir / "uv"
    uv.write_text(STAND_IN_UV)
    uv.chmod(0o755)
    log = tmp_path / "uv-call.json"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update({
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "STAND_IN_LOG": str(log),
        "STAND_IN_EXIT": str(exit_code),
        # the caller's own database address must not reach the engine's runner
        "DATABASE_URL": "postgresql://someone:secret@127.0.0.1:5432/platform",
    })
    r = subprocess.run([str(SCRIPT), *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
    call = json.loads(log.read_text()) if log.is_file() else None
    return r, call


# the script itself


def test_the_script_is_an_executable_strict_bash_script():
    assert SCRIPT.is_file(), f"{SCRIPT.relative_to(ROOT)} is missing"
    assert os.access(SCRIPT, os.X_OK), "the script is not executable"
    text = SCRIPT.read_text()
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text
    r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_the_script_never_sets_pythonpath():
    """The vendored wheels must be enough for the engine's imports."""
    assert "PYTHONPATH" not in SCRIPT.read_text()


def test_the_postgres_mode_uses_the_throwaway_database_helper():
    text = SCRIPT.read_text()
    assert "throwaway-pg.sh" in text
    assert "5432" not in text


# sqlite mode, with the stand-in uv


@needs_backend
def test_the_labels_are_the_test_packages_and_modules_without_integration():
    labels = expected_labels()
    assert len(labels) == 36, labels
    assert "aisc_backend.tests.integration" not in labels


@needs_backend
def test_sqlite_mode_runs_the_engine_runner_on_every_label_in_order(tmp_path):
    r, call = run_with_stand_in(tmp_path)
    assert r.returncode == 0, r.stderr
    assert call is not None, "the script never called uv"
    assert call["argv"] == RUNNER + expected_labels()
    assert Path(call["cwd"]).resolve() == BACKEND.resolve()


@needs_backend
def test_sqlite_mode_runs_on_a_fresh_sqlite_file_removed_afterwards(tmp_path):
    r, call = run_with_stand_in(tmp_path)
    assert r.returncode == 0, r.stderr
    env = call["env"]
    assert env.get("DB_ENGINE") == "django.db.backends.sqlite3"
    db_name = Path(env["DB_NAME"])
    assert db_name.name == "engine-tests.db"
    assert call["db_folder_existed"], "the sqlite file's folder did not exist during the run"
    assert not db_name.parent.exists(), "the sqlite file's folder was left behind"
    assert db_name.parent.resolve() != BACKEND.resolve()


@needs_backend
def test_sqlite_mode_drops_the_callers_database_url_and_sets_no_pythonpath(tmp_path):
    r, call = run_with_stand_in(tmp_path)
    assert r.returncode == 0, r.stderr
    assert "DATABASE_URL" not in call["env"]
    assert "PYTHONPATH" not in call["env"]
    assert call["env"].get("AISC_DEPLOYMENT") != "configurator"


@needs_backend
def test_extra_arguments_reach_the_runner_after_the_labels(tmp_path):
    r, call = run_with_stand_in(tmp_path, "-v", "2", "--failfast")
    assert r.returncode == 0, r.stderr
    assert call["argv"] == RUNNER + expected_labels() + ["-v", "2", "--failfast"]


@needs_backend
def test_the_script_runs_the_same_from_another_folder(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    r, call = run_with_stand_in(tmp_path, cwd=elsewhere)
    assert r.returncode == 0, r.stderr
    assert call["argv"] == RUNNER + expected_labels()
    assert Path(call["cwd"]).resolve() == BACKEND.resolve()


@needs_backend
def test_the_exit_code_is_the_runners(tmp_path):
    r, call = run_with_stand_in(tmp_path, exit_code=3)
    assert call is not None
    assert r.returncode == 3


# real runs


def engine(*args: str, cwd: Path = ROOT, script: Path = SCRIPT, timeout: int = 900):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "DATABASE_URL")}
    return subprocess.run([str(script), *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


def last_lines(r) -> list[str]:
    return [line for line in (r.stdout + r.stderr).splitlines() if line.strip()][-2:]


TEST_ID = re.compile(r"^\w+ \((aisc_backend\.tests\.[\w.]+)\)", re.M)


@pytest.fixture(scope="module")
def verbose_run():
    return engine("-v", "2")


@real_runs
@needs_backend
def test_a_real_sqlite_run_passes_without_the_integration_package():
    r = engine()
    assert r.returncode == 0, (r.stdout + r.stderr)[-4000:]
    ran, verdict = last_lines(r)
    assert ran.startswith("Ran 576 tests") and verdict == "OK (skipped=134)", (ran, verdict)
    assert "aisc_backend.tests.integration" not in r.stdout + r.stderr


@real_runs
@needs_backend
def test_a_real_verbose_run_names_every_label_and_one_line_per_test(verbose_run):
    r = verbose_run
    output = r.stdout + r.stderr
    assert r.returncode == 0, output[-4000:]
    ids = TEST_ID.findall(output)
    assert len(ids) == 576, len(ids)
    labels = expected_labels()
    assert len(labels) == 36
    unlabelled = [i for i in ids if not any(i == lab or i.startswith(lab + ".") for lab in labels)]
    assert not unlabelled, unlabelled[:10]
    empty = [lab for lab in labels if not any(i == lab or i.startswith(lab + ".") for i in ids)]
    assert not empty, f"labels with no test: {empty}"
    assert not [i for i in ids if i.startswith("aisc_backend.tests.integration")]
    assert "OK (skipped=134)" in output


@real_runs
@needs_backend
def test_a_real_run_from_another_folder_gives_the_same_totals(tmp_path):
    r = engine(cwd=tmp_path)
    output = r.stdout + r.stderr
    assert r.returncode == 0, output[-4000:]
    assert re.search(r"^Ran 576 tests in ", output, re.M), output[-2000:]
    assert "OK (skipped=134)" in output


def containers(prefix: str) -> list[str]:
    r = subprocess.run(["docker", "ps", "-a", "--filter", f"name={prefix}", "--format", "{{.Names}}"],
                       capture_output=True, text=True)
    return r.stdout.split()


CONTAINER_LINE = re.compile(r"throwaway-pg: container (aisc-t-engine-\w+) on 127\.0\.0\.1:(\d+)")


@real_runs
@needs_backend
@needs_docker
def test_a_real_postgres_run_runs_every_database_test_and_removes_its_container():
    r = engine("--postgres", timeout=1800)
    output = r.stdout + r.stderr
    assert r.returncode == 0, output[-4000:]
    assert re.search(r"^Ran 45 tests in ", output, re.M), output[-2000:]
    assert re.search(r"^OK$", output, re.M), output[-2000:]
    assert "skipped=" not in output
    started = CONTAINER_LINE.search(output)
    assert started, "no aisc-t-engine container was started"
    name, port = started.groups()
    assert port != "5432"
    assert name not in containers("aisc-t-engine")


def scratch_root(tmp_path: Path, script_text: str) -> Path:
    """A checkout made of links to this one, with its own copy of the script."""
    root = tmp_path / "root"
    root.mkdir()
    for entry in ROOT.iterdir():
        if entry.name != "scripts":
            (root / entry.name).symlink_to(entry)
    (root / "scripts").mkdir()
    for entry in (ROOT / "scripts").iterdir():
        if entry.name != "lib":
            (root / "scripts" / entry.name).symlink_to(entry)
    (root / "scripts/lib").mkdir()
    for entry in (ROOT / "scripts/lib").iterdir():
        if entry.name != "engine-tests.sh":
            (root / "scripts/lib" / entry.name).symlink_to(entry)
    copy = root / "scripts/lib/engine-tests.sh"
    copy.write_text(script_text)
    copy.chmod(0o755)
    return root


@real_runs
@needs_backend
@needs_docker
def test_a_postgres_run_whose_database_tests_all_skip_fails(tmp_path):
    text = SCRIPT.read_text()
    assert "AISC_DEPLOYMENT=configurator" in text
    root = scratch_root(tmp_path, text.replace("AISC_DEPLOYMENT=configurator", "AISC_DEPLOYMENT_UNUSED=configurator"))
    r = engine("--postgres", cwd=tmp_path, script=root / "scripts/lib/engine-tests.sh", timeout=1800)
    output = r.stdout + r.stderr
    assert "OK (skipped=45)" in output, output[-2000:]
    assert ("engine-tests: 45 database tests skipped: the throwaway database did not reach them"
            in r.stderr.splitlines()), r.stderr[-2000:]
    assert r.returncode == 1
    assert not [n for n in containers("aisc-t-engine") if n in output]
