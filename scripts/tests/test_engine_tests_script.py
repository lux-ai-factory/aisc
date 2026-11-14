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
with open(os.environ["STAND_IN_LOG"], "a") as f:
    f.write(json.dumps(record) + "\n")
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


#: What marks a module whose tests run only in the Configurator (isolation_support.configurator_only and the
#: per-module skips); the script's configurator pass runs those modules with AISC_DEPLOYMENT=configurator.
CONFIGURATOR_MARK = re.compile(r"configurator_only|configurator_run|_CONFIGURATOR_RUN|skipIf\(_STANDALONE_RUN")
SUPERUSER_MARK = re.compile(r"SUPERUSER_URL_VAR|superuser_url")


def configurator_labels() -> list[str]:
    """The test modules, in the packages too, with configurator-only tests that need no Postgres superuser (those
    run in --postgres), as dotted labels, sorted."""
    files = [f for f in TESTS.rglob("test_*.py") if "integration" not in f.relative_to(TESTS).parts]
    picked = [f for f in files if CONFIGURATOR_MARK.search(f.read_text()) and not SUPERUSER_MARK.search(f.read_text())]
    return sorted("aisc_backend.tests." + ".".join(f.relative_to(TESTS).with_suffix("").parts) for f in picked)


def run_all_with_stand_in(tmp_path: Path, *args: str, cwd: Path = ROOT, exit_code: int = 0):
    """The script's run with the stand-in uv: (result, every call it made, in order)."""
    r, _ = run_with_stand_in(tmp_path, *args, cwd=cwd, exit_code=exit_code)
    log = tmp_path / "uv-call.json"
    return r, [json.loads(line) for line in log.read_text().splitlines()] if log.is_file() else []


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
    log.unlink(missing_ok=True)
    r = subprocess.run([str(SCRIPT), *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
    call = json.loads(log.read_text().splitlines()[0]) if log.is_file() else None
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
    assert "aisc_backend.tests.routers" in labels and "aisc_backend.tests.test_ledger_events" in labels, labels
    assert len(labels) == len(set(labels))
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


# the Configurator's own tests (the door, isolation, the modes), which a standalone run skips


@needs_backend
def test_the_configurator_pass_is_the_modules_whose_tests_are_configurator_only():
    labels = configurator_labels()
    for label in ("aisc_backend.tests.routers.test_project_membership", "aisc_backend.tests.test_isolation_engine",
                  "aisc_backend.tests.test_every_project_route_is_guarded", "aisc_backend.tests.test_modes_routes"):
        assert label in labels, label
    assert "aisc_backend.tests.test_isolation_engine_db" not in labels, "a superuser module runs in --postgres"
    assert "aisc_backend.tests.test_ledger_events" not in labels


@needs_backend
def test_sqlite_mode_runs_the_configurator_only_modules_again_in_configurator_mode(tmp_path):
    r, calls = run_all_with_stand_in(tmp_path)
    assert r.returncode == 0, r.stderr
    assert len(calls) == 2, calls
    standalone, configurator = calls
    assert standalone["env"].get("AISC_DEPLOYMENT") != "configurator"
    assert configurator["argv"] == RUNNER + configurator_labels()
    assert configurator["env"].get("AISC_DEPLOYMENT") == "configurator"
    assert configurator["env"].get("DB_ENGINE") == "django.db.backends.sqlite3"
    assert "DATABASE_URL" not in configurator["env"]
    assert configurator["db_folder_existed"]


@needs_backend
def test_a_failing_standalone_pass_still_runs_the_configurator_pass_and_fails(tmp_path):
    r, calls = run_all_with_stand_in(tmp_path, exit_code=3)
    assert len(calls) == 2
    assert r.returncode == 3


@needs_backend
def test_labels_given_narrow_the_run_to_them(tmp_path):
    r, calls = run_all_with_stand_in(tmp_path, "aisc_backend.tests.test_ledger_events", "-v", "2")
    assert r.returncode == 0, r.stderr
    assert [c["argv"] for c in calls] == [RUNNER + ["aisc_backend.tests.test_ledger_events", "-v", "2"]]


@needs_backend
def test_files_given_narrow_the_run_and_a_configurator_module_runs_in_both_modes(tmp_path):
    r, calls = run_all_with_stand_in(tmp_path, "apps/backend/aisc_backend/tests/routers/test_project_membership.py",
                                     "aisc_backend/tests/test_ledger_events.py")
    assert r.returncode == 0, r.stderr
    membership, events = "aisc_backend.tests.routers.test_project_membership", "aisc_backend.tests.test_ledger_events"
    assert [c["argv"] for c in calls] == [RUNNER + [membership, events], RUNNER + [membership]]
    assert calls[1]["env"].get("AISC_DEPLOYMENT") == "configurator"


@needs_backend
def test_a_label_that_names_no_test_module_is_refused(tmp_path):
    r, calls = run_all_with_stand_in(tmp_path, "aisc_backend/tests/test_no_such_module.py")
    assert r.returncode == 2 and calls == []
    assert "test_no_such_module" in r.stderr


# real runs


def engine(*args: str, cwd: Path = ROOT, script: Path = SCRIPT, timeout: int = 900):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "DATABASE_URL")}
    return subprocess.run([str(script), *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


TEST_ID = re.compile(r"^\w+ \((aisc_backend\.tests\.[\w.]+)\)", re.M)
RAN = re.compile(r"^Ran (\d+) tests? in ", re.M)
SUMMARY = re.compile(r"^(OK|FAILED)(?: \((.*)\))?$", re.M)


def passes(text: str) -> list[tuple[int, int]]:
    """(tests run, tests skipped) of each manage.py test pass in a run's output, in order; each pass ends with
    a `Ran N tests` line and its summary (`OK`, `OK (skipped=K)`)."""
    ran = [int(n) for n in RAN.findall(text)]
    summaries = SUMMARY.findall(text)
    assert len(ran) == len(summaries), text[-2000:]
    skipped = [int(m.group(1)) if (m := re.search(r"skipped=(\d+)", detail)) else 0 for _, detail in summaries]
    assert all(verdict == "OK" for verdict, _ in summaries), text[-2000:]
    return list(zip(ran, skipped))


def postgres_labels() -> list[str]:
    """The modules --postgres runs: those directly under aisc_backend/tests that need a Postgres superuser."""
    return sorted(f"aisc_backend.tests.{f.stem}" for f in TESTS.glob("*.py")
                  if f.stem != "isolation_support" and SUPERUSER_MARK.search(f.read_text()))


def under(test_id: str, labels: list[str]) -> bool:
    return any(test_id == lab or test_id.startswith(lab + ".") for lab in labels)


@pytest.fixture(scope="module")
def verbose_run():
    return engine("-v", "2")


@real_runs
@needs_backend
def test_a_real_sqlite_run_passes_both_modes_without_the_integration_package():
    r = engine()
    output = r.stdout + r.stderr
    assert r.returncode == 0, output[-4000:]
    # the standalone pass, then the configurator pass; each ran tests and did not skip them all
    totals = passes(r.stderr)
    assert len(totals) == 2, totals
    assert all(0 < ran and skipped < ran for ran, skipped in totals), totals
    assert "aisc_backend.tests.integration" not in output


@real_runs
@needs_backend
def test_a_real_verbose_run_names_every_label_and_one_line_per_test(verbose_run):
    r = verbose_run
    output = r.stdout + r.stderr
    assert r.returncode == 0, output[-4000:]
    totals = passes(r.stderr)
    assert len(totals) == 2, totals
    first_pass_end = RAN.search(r.stderr).end()
    standalone, configurator = TEST_ID.findall(r.stderr[:first_pass_end]), TEST_ID.findall(r.stderr[first_pass_end:])
    assert (len(standalone), len(configurator)) == (totals[0][0], totals[1][0])
    for ids, labels in ((standalone, expected_labels()), (configurator, configurator_labels())):
        assert labels
        unlabelled = [i for i in ids if not under(i, labels)]
        assert not unlabelled, unlabelled[:10]
        empty = [lab for lab in labels if not any(under(i, [lab]) for i in ids)]
        assert not empty, f"labels with no test: {empty}"
    assert not [i for i in standalone + configurator if i.startswith("aisc_backend.tests.integration")]


@real_runs
@needs_backend
def test_a_real_run_from_another_folder_gives_the_same_totals(tmp_path, verbose_run):
    r = engine(cwd=tmp_path)
    output = r.stdout + r.stderr
    assert r.returncode == 0, output[-4000:]
    assert passes(r.stderr) == passes(verbose_run.stderr)


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
    # every module that needs a superuser ran, and none of its tests skipped
    [(ran, skipped)] = passes(output)
    assert ran >= len(postgres_labels()) > 0
    assert skipped == 0 and "skipped=" not in output
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
    # outside configurator mode the database tests skip; the run says so with their number and fails
    [(ran, skipped)] = passes(output)
    assert 0 < skipped <= ran, (ran, skipped)
    assert (f"engine-tests: {skipped} database tests skipped: the throwaway database did not reach them"
            in r.stderr.splitlines()), r.stderr[-2000:]
    assert r.returncode == 1
    assert not [n for n in containers("aisc-t-engine") if n in output]
