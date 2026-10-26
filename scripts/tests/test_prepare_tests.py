"""scripts/prepare-tests.sh: the one way to prepare a checkout for scripts/tests, and its --check mode.

Every case runs a copy of the script in a scratch root (a tmp folder with the module folders made by the
test), never in this checkout. node, npm and uv are stand-ins in tmp_path/bin that append
`<tool> <args> @ <cwd relative to the scratch root>` to tmp_path/calls.log; the rest of PATH is a folder of
links to the system's tools without node, npm, npx or uv, so no real one is ever found.

Also: CI's repository checks and the guide's Tests section call the script instead of repeating it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from conftest import ROOT

SCRIPT = ROOT / "scripts/prepare-tests.sh"
NODE_MODULES = ("apps/qualification", "apps/controls")
UV_MODULES = ("apps/backend", "apps/control-objectives", "apps/report-composer")
#: tools a real environment would offer that the scratch PATH must not
HIDDEN_TOOLS = {"node", "nodejs", "npm", "npx", "uv", "uvx", "corepack"}

ALL_MISSING = (
    "apps/qualification has no node_modules: run scripts/prepare-tests.sh\n"
    "apps/controls has no node_modules: run scripts/prepare-tests.sh\n"
    "apps/backend has no .venv: run scripts/prepare-tests.sh\n"
    "apps/control-objectives has no .venv: run scripts/prepare-tests.sh\n"
    "apps/report-composer has no .venv: run scripts/prepare-tests.sh\n"
)
INSTALL_CALLS = [
    "npm ci --no-audit --no-fund @ apps/qualification",
    "npm ci --no-audit --no-fund @ apps/controls",
    "uv sync --locked --all-extras @ apps/backend",
    "uv sync --locked --all-extras @ apps/control-objectives",
    "uv sync --locked --all-extras @ apps/report-composer",
]


@pytest.fixture(scope="session")
def system_bin(tmp_path_factory) -> Path:
    """Links to every tool of /usr/bin and /bin except node, npm and uv."""
    d = tmp_path_factory.mktemp("system-bin")
    for folder in (Path("/usr/bin"), Path("/bin")):
        for tool in sorted(folder.iterdir()):
            if tool.name in HIDDEN_TOOLS or (d / tool.name).exists() or (d / tool.name).is_symlink():
                continue
            try:
                runnable = tool.is_file() and os.access(tool, os.X_OK)
            except OSError:  # a tool this user may not even look at
                runnable = False
            if runnable:
                (d / tool.name).symlink_to(tool)
    return d


def make_root(base: Path, *, environments: bool = False) -> Path:
    """A scratch root: the script copied in, the five modules with their manifests; with environments,
    node_modules/ in the Node modules and .venv/bin/python in the uv modules."""
    if not SCRIPT.exists():
        pytest.fail("scripts/prepare-tests.sh missing")
    root = base / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, root / "scripts/prepare-tests.sh")
    for m in NODE_MODULES:
        (root / m).mkdir(parents=True)
        (root / m / "package.json").write_text("{}\n")
        if environments:
            (root / m / "node_modules").mkdir()
    for m in UV_MODULES:
        (root / m).mkdir(parents=True)
        (root / m / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        if environments:
            (root / m / ".venv/bin").mkdir(parents=True)
            (root / m / ".venv/bin/python").write_text("")
            (root / m / ".venv/bin/python").chmod(0o755)
    return root


def stand_in(tmp_path: Path, root: Path, tool: str, fail_in: str | None = None) -> None:
    """tmp_path/bin/<tool>: records its call in tmp_path/calls.log; exits 1 when run in `fail_in`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    real_root = root.resolve()
    fail = f'[ "$rel" = "{fail_in}" ] && exit 1\n' if fail_in else ""
    script = (
        "#!/usr/bin/env bash\n"
        'here=$(pwd -P)\n'
        f'if [ "$here" = "{real_root}" ]; then rel=.; else rel=${{here#{real_root}/}}; fi\n'
        f'echo "{tool} $* @ $rel" >> "{tmp_path / "calls.log"}"\n'
        f"{fail}"
        "exit 0\n"
    )
    (bin_dir / tool).write_text(script)
    (bin_dir / tool).chmod(0o755)


def stand_ins(tmp_path: Path, root: Path, tools=("node", "npm", "uv"), **kw) -> None:
    (tmp_path / "bin").mkdir(exist_ok=True)
    for tool in tools:
        stand_in(tmp_path, root, tool, **kw.get(tool, {}))


def prepare(root: Path, tmp_path: Path, system_bin: Path, *args: str, cwd: Path | None = None):
    env = {"PATH": f"{tmp_path / 'bin'}:{system_bin}", "HOME": str(tmp_path)}
    return subprocess.run([str(root / "scripts/prepare-tests.sh"), *args], cwd=cwd or root, env=env,
                          capture_output=True, text=True, timeout=120)


def calls(tmp_path: Path) -> list[str]:
    return (tmp_path / "calls.log").read_text().splitlines()


def files_under(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


# --check


def test_check_lists_every_missing_environment_in_module_order(tmp_path, system_bin):
    root = make_root(tmp_path)
    stand_ins(tmp_path, root)
    r = prepare(root, tmp_path, system_bin, "--check")
    assert r.returncode == 1, r.stderr
    assert r.stdout == ALL_MISSING


def test_check_is_silent_and_passes_when_every_environment_is_there(tmp_path, system_bin):
    root = make_root(tmp_path, environments=True)
    stand_ins(tmp_path, root)
    r = prepare(root, tmp_path, system_bin, "--check")
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


def test_check_names_a_module_that_is_not_checked_out(tmp_path, system_bin):
    root = make_root(tmp_path)
    (root / "apps/controls/package.json").unlink()
    stand_ins(tmp_path, root)
    r = prepare(root, tmp_path, system_bin, "--check")
    assert r.returncode == 1, r.stderr
    assert r.stdout == ALL_MISSING.replace(
        "apps/controls has no node_modules: run scripts/prepare-tests.sh",
        "apps/controls is not checked out: git submodule update --init apps/controls")


def test_check_needs_no_node_npm_or_uv(tmp_path, system_bin):
    root = make_root(tmp_path)
    (tmp_path / "bin").mkdir()
    r = prepare(root, tmp_path, system_bin, "--check")
    assert r.returncode == 1, r.stderr
    assert r.stdout == ALL_MISSING


def test_check_writes_nothing_and_calls_no_tool(tmp_path, system_bin):
    root = make_root(tmp_path)
    stand_ins(tmp_path, root)
    before = files_under(root)
    prepare(root, tmp_path, system_bin, "--check")
    assert files_under(root) == before
    assert not (tmp_path / "calls.log").exists()


# install mode


def test_install_prepares_every_module_in_order(tmp_path, system_bin):
    root = make_root(tmp_path)
    stand_ins(tmp_path, root)
    r = prepare(root, tmp_path, system_bin)
    assert r.returncode == 0, r.stderr
    assert calls(tmp_path) == INSTALL_CALLS
    assert r.stdout.splitlines() == [f"prepared {m}" for m in NODE_MODULES + UV_MODULES]


def test_install_works_on_the_scripts_repo_from_any_directory(tmp_path, system_bin):
    root = make_root(tmp_path)
    stand_ins(tmp_path, root)
    r = prepare(root, tmp_path, system_bin, cwd=tmp_path / "bin")
    assert r.returncode == 0, r.stderr
    assert calls(tmp_path) == INSTALL_CALLS


def test_install_stops_at_the_first_failing_command(tmp_path, system_bin):
    root = make_root(tmp_path)
    stand_ins(tmp_path, root, uv={"fail_in": "apps/control-objectives"})
    r = prepare(root, tmp_path, system_bin)
    assert r.returncode == 1
    assert "prepare-tests: uv sync --locked --all-extras failed in apps/control-objectives" in r.stderr
    assert calls(tmp_path) == INSTALL_CALLS[:4]


def test_install_without_npm_names_node_and_npm(tmp_path, system_bin):
    root = make_root(tmp_path)
    stand_ins(tmp_path, root, tools=("node", "uv"))
    r = prepare(root, tmp_path, system_bin)
    assert r.returncode == 1
    assert r.stderr.strip() == ("prepare-tests: node and npm are needed (Node.js 20) for apps/qualification "
                                "and apps/controls")
    assert not (tmp_path / "calls.log").exists()


def test_install_without_uv_names_uv(tmp_path, system_bin):
    root = make_root(tmp_path)
    stand_ins(tmp_path, root, tools=("node", "npm"))
    r = prepare(root, tmp_path, system_bin)
    assert r.returncode == 1
    assert r.stderr.strip() == ("prepare-tests: uv is needed for apps/backend, apps/control-objectives and "
                                "apps/report-composer")
    assert not (tmp_path / "calls.log").exists()


def test_install_refuses_a_module_that_is_not_checked_out(tmp_path, system_bin):
    root = make_root(tmp_path)
    (root / "apps/report-composer/pyproject.toml").unlink()
    stand_ins(tmp_path, root)
    r = prepare(root, tmp_path, system_bin)
    assert r.returncode == 1
    assert ("prepare-tests: apps/report-composer is not checked out: git submodule update --init "
            "apps/report-composer") in r.stderr
    assert not (tmp_path / "calls.log").exists()


def test_an_unknown_argument_prints_the_usage(tmp_path, system_bin):
    root = make_root(tmp_path)
    stand_ins(tmp_path, root)
    r = prepare(root, tmp_path, system_bin, "--nonsense")
    assert r.returncode == 2
    assert r.stderr.strip() == "usage: scripts/prepare-tests.sh [--check]"


def test_the_script_is_an_executable_strict_bash_script():
    assert SCRIPT.exists(), "scripts/prepare-tests.sh missing"
    assert os.access(SCRIPT, os.X_OK)
    text = SCRIPT.read_text()
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text
    r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# CI and the guide call the script


def test_ci_repository_checks_prepare_with_the_script():
    steps = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]["repository-checks"]["steps"]
    runs = [str(s.get("run", "")) for s in steps]
    prepare_at = [i for i, run in enumerate(runs) if run.strip() == "scripts/prepare-tests.sh"]
    pytest_at = [i for i, run in enumerate(runs) if "python -m pytest" in run]
    assert prepare_at, "no step of repository-checks runs scripts/prepare-tests.sh"
    assert pytest_at and prepare_at[0] < pytest_at[0], "scripts/prepare-tests.sh must run before pytest"
    assert not [run for run in runs if "npm ci" in run or "uv sync" in run], \
        "repository-checks still repeats the preparation"


def test_the_guide_prepares_with_the_script():
    text = (ROOT / "docs/guide.md").read_text()
    start = text.index("\n## Tests\n")
    end = text.find("\n## ", start + 1)
    section = text[start:end if end != -1 else len(text)]
    assert "scripts/prepare-tests.sh" in section
    assert "scripts/prepare-tests.sh --check" in section
    assert "npm ci" not in section
    assert "uv sync" not in section
