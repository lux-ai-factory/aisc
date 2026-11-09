"""scripts/suites.py is the one list of how each module's tests run. verify.sh --modules runs its rows and the
root CI's python matrix holds exactly the rows marked for CI, with the same commands, so the two cannot drift
apart again: a suite added to one and not the other fails here.

Read-only: nothing is run but `scripts/suites.py rows`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import suites  # noqa: E402

CI = ROOT / ".github/workflows/ci.yml"


def python_matrix() -> dict[str, str]:
    include = yaml.safe_load(CI.read_text())["jobs"]["python"]["strategy"]["matrix"]["include"]
    return {entry["suite"]: str(entry["run"]) for entry in include}


def test_the_ci_python_matrix_is_the_registrys_ci_rows():
    assert python_matrix() == {s.name: s.command for s in suites.SUITES if s.ci}


def test_every_rows_folder_exists():
    for s in suites.SUITES:
        assert (ROOT / s.dir).is_dir(), f"{s.name}: no folder {s.dir}"


def test_names_are_unique_and_fields_hold_no_separator():
    names = [s.name for s in suites.SUITES]
    assert len(names) == len(set(names)), names
    for s in suites.SUITES:
        for field in (s.name, s.dir, s.marker, *s.needs):
            assert "|" not in field and "\n" not in field, (s.name, field)
        assert "\n" not in s.command, s.name


def test_every_module_with_tests_has_a_row():
    """Each public submodule CI checks out, and each root module with tests, is run by at least one row."""
    modules = yaml.safe_load(CI.read_text())["env"]["PUBLIC_SUBMODULES"].split()
    modules += ["platform", "shared/identity", "apps/report-composer", "dashboard-gateway"]
    for module in modules:
        assert any(s.dir == module or s.dir.startswith(module + "/") for s in suites.SUITES), f"no row runs {module}"


def test_the_engine_runs_through_its_script_from_the_lock():
    engine = next(s for s in suites.SUITES if s.name == "engine")
    assert engine.command == "scripts/lib/engine-tests.sh"


def test_the_plugin_interface_runs_with_onnx_as_its_own_ci_does():
    row = next(s for s in suites.SUITES if s.name == "plugin-interface")
    assert "--with onnx --with onnxruntime" in row.command
    own = (ROOT / "shared/plugin-interface/.github/workflows/ci.yml").read_text()
    assert "--with onnx --with onnxruntime" in own


def test_rows_prints_one_line_per_suite_that_verify_reads():
    out = subprocess.run([sys.executable, str(ROOT / "scripts/suites.py"), "rows"], capture_output=True, text=True,
                         check=True).stdout
    lines = out.splitlines()
    assert len(lines) == len(suites.SUITES)
    for line, s in zip(lines, suites.SUITES):
        # the shell splits the first four fields at `|`; the command keeps whatever follows
        name, directory, marker, needs, command = line.split("|", 4)
        assert (name, directory, marker, needs.split(","), command) == (
            s.name, s.dir, s.marker, list(s.needs) or [""], s.command)


def test_an_unknown_argument_is_refused():
    r = subprocess.run([sys.executable, str(ROOT / "scripts/suites.py"), "row"], capture_output=True, text=True)
    assert r.returncode == 2 and "usage" in r.stderr


def test_verify_takes_its_modules_from_the_registry():
    text = (ROOT / "scripts/verify.sh").read_text()
    assert "<<'MODULES'" not in text
    assert "scripts/suites.py rows" in text


#: compose build contexts that hold tests no row runs, with why
NO_ROW = {}
SKIPPED_FOLDERS = {"node_modules", ".venv", ".git", "__pycache__", "build", "dist"}


def compose_build_contexts() -> set[str]:
    """Every folder a compose file builds an image from, from the repository root (a ${VAR:-default} as its
    default)."""
    found = set()
    for f in sorted(ROOT.glob("docker-compose*.yml")):
        for service in (yaml.safe_load(f.read_text()).get("services") or {}).values():
            build = service.get("build")
            if build is None:
                continue
            context = build if isinstance(build, str) else build.get("context", ".")
            context = re.sub(r"\$\{[A-Z_]+:-([^}]*)\}", r"\1", context)
            found.add(str(Path(context)))
    return found


def holds_tests(folder: Path) -> bool:
    """A tests/ or test/ folder, or a test file (test_*.py, *_test.py, *.test.* or *.spec.*), outside installed
    dependencies."""
    for here, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIPPED_FOLDERS]
        if {"tests", "test"} & set(dirs):
            return True
        if any(re.match(r"^(test_.+\.py|.+_test\.py|.+\.(test|spec)\.[cm]?[jt]sx?)$", f) for f in files):
            return True
    return False


def test_every_compose_built_folder_with_tests_has_a_row():
    """A module with tests and an image the stack builds is run by a row (its folder, one above it or one inside
    it), or is named in NO_ROW with the reason; so a new module is not left to a hand-written list."""
    missing = []
    for context in sorted(compose_build_contexts()):
        if not (ROOT / context).is_dir() or not holds_tests(ROOT / context) or context in NO_ROW:
            continue
        if not any(s.dir == context or context.startswith(s.dir + "/") or s.dir.startswith(context + "/")
                   for s in suites.SUITES):
            missing.append(context)
    assert missing == []
    for context in NO_ROW:
        assert holds_tests(ROOT / context), f"{context} holds no tests any more: take it off NO_ROW"


def test_beds_lists_the_module_environments_prepare_tests_makes():
    out = subprocess.run([sys.executable, str(ROOT / "scripts/suites.py"), "beds"], capture_output=True, text=True,
                         check=True).stdout
    assert out == ("npm apps/qualification\nnpm apps/controls\n"
                   "uv apps/control-objectives\nuv apps/report-composer\nuv apps/backend\n")
