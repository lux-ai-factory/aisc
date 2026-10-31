"""scripts/suites.py is the one list of how each module's tests run. verify.sh --modules runs its rows and the
root CI's python matrix holds exactly the rows marked for CI, with the same commands, so the two cannot drift
apart again: a suite added to one and not the other fails here.

Read-only: nothing is run but `scripts/suites.py rows`.
"""

from __future__ import annotations

import subprocess
import sys

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
