"""The isolation bed names a missing module environment and a failing command's error line.

No Postgres: environment_problems runs scripts/prepare-tests.sh --check on a scratch root, _python reads
a scratch root, error_line and _run read text.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import isolation_bed as ib
from test_prepare_tests import make_root

ALL_MISSING = {
    "qualification": "apps/qualification has no node_modules: run scripts/prepare-tests.sh",
    "controls": "apps/controls has no node_modules: run scripts/prepare-tests.sh",
    "engine": "apps/backend has no .venv: run scripts/prepare-tests.sh",
    "control_objectives": "apps/control-objectives has no .venv: run scripts/prepare-tests.sh",
    "report_composer": "apps/report-composer has no .venv: run scripts/prepare-tests.sh",
}

NODE_MISSING_PACKAGE = (
    "node:internal/modules/esm/resolve:873\n"
    "  throw new ERR_MODULE_NOT_FOUND(packageName, fileURLToPath(base), null);\n"
    "        ^\n"
    "\n"
    "Error [ERR_MODULE_NOT_FOUND]: Cannot find package 'pg' imported from /x/apps/controls/scripts/migrate-projects.mjs\n"
    "    at packageResolve (node:internal/modules/esm/resolve:873:9) {\n"
    "  code: 'ERR_MODULE_NOT_FOUND'\n"
    "}\n"
    "\n"
    "Node.js v20.20.2\n"
)


def test_environment_problems_names_every_missing_environment_by_its_bed_key(tmp_path):
    root = make_root(tmp_path)
    assert ib.environment_problems(root) == ALL_MISSING


def test_environment_problems_is_empty_on_a_prepared_root(tmp_path):
    root = make_root(tmp_path, environments=True)
    assert ib.environment_problems(root) == {}


def test_environment_problems_names_a_missing_script(tmp_path):
    assert ib.environment_problems(tmp_path) == {"environment": "scripts/prepare-tests.sh missing"}


def test_python_never_falls_back_to_another_checkout(tmp_path, monkeypatch):
    home = tmp_path / "home"
    other = home / "aisc-install/apps/control-objectives/.venv/bin/python"
    other.parent.mkdir(parents=True)
    other.write_text("")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    root = tmp_path / "root"
    (root / "apps/control-objectives").mkdir(parents=True)
    assert ib._python("apps/control-objectives", root) == ""
    assert not hasattr(ib, "INSTALL")


def test_python_is_the_roots_own_virtualenv(tmp_path):
    py = tmp_path / "apps/control-objectives/.venv/bin/python"
    py.parent.mkdir(parents=True)
    py.write_text("")
    assert ib._python("apps/control-objectives", tmp_path) == str(py)


def test_error_line_is_nodes_error_not_its_version_line():
    assert ib.error_line(NODE_MISSING_PACKAGE) == (
        "Error [ERR_MODULE_NOT_FOUND]: Cannot find package 'pg' imported from "
        "/x/apps/controls/scripts/migrate-projects.mjs")


def test_error_line_is_pythons_exception_line():
    assert ib.error_line("Traceback (most recent call last):\n  File \"x\", line 1\n"
                         "ModuleNotFoundError: No module named 'sqlalchemy'\n") == \
        "ModuleNotFoundError: No module named 'sqlalchemy'"


def test_error_line_without_an_error_is_the_last_line():
    assert ib.error_line("migrating project_a\n\nall done\n") == "all done"
    assert ib.error_line("") == "?"


def test_run_names_the_error_line_even_outside_the_kept_log(tmp_path):
    bed = SimpleNamespace(problems={}, logs={}, t=SimpleNamespace(password="pw"))
    code = ("import sys\n"
            "print('Error: boom')\n"
            "for _ in range(60): print('a' * 50)\n"
            "print('Node.js v20.20.2')\n"
            "sys.exit(1)\n")
    ib._run(bed, "controls", [sys.executable, "-c", code], tmp_path, {}, "why")
    assert bed.problems["controls"] == "why (exit 1): Error: boom"
    assert len(bed.logs["controls"]) <= 1500
