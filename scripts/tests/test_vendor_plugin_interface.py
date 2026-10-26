"""scripts/vendor-plugin-interface.sh: builds one wheel of shared/plugin-interface, copies it under vendor/
in the backend, the eval worker, the plugin-manager and each plugin repo it is given, and relocks each.

Every case runs a copy of the script in a scratch root: a copy of shared/plugin-interface (its own git
repo, committed, as the submodule is) and small target projects. Nothing is written into the checkout.
The locking cases need PyPI for pydantic and rich, or uv's cache.

Run from the repo root:

    uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_vendor_plugin_interface.py
"""

import hashlib
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from conftest import ROOT

SCRIPT = ROOT / "scripts/vendor-plugin-interface.sh"
WHEEL = "aisc_plugin_interface-0.4.0-py3-none-any.whl"
TARGETS = ("apps/backend", "apps/eval", "shared/plugin-manager")
SOURCE_LINE = f'aisc-plugin-interface = {{ path = "vendor/{WHEEL}" }}'
VENDORED = re.compile(rf"^vendored {re.escape(WHEEL)} into (.+); its lock names 0\.4\.0 from vendor/$")


def _pyproject(name: str, with_source: bool = True) -> str:
    text = (f'[project]\nname = "{name}"\nversion = "0.0.1"\nrequires-python = ">=3.12"\n'
            f'dependencies = ["aisc-plugin-interface>=0.4.0"]\n')
    if with_source:
        text += f"\n[tool.uv.sources]\n{SOURCE_LINE}\n"
    return text


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                   cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def scratch(tmp_path):
    """A scratch root holding the script, a committed copy of the interface and the three targets,
    plus one plugin repo outside it. Returns (root, plugin repo)."""
    root = tmp_path / "aisc"
    (root / "scripts").mkdir(parents=True)
    if SCRIPT.exists():
        shutil.copy2(SCRIPT, root / "scripts" / SCRIPT.name)
    interface = root / "shared/plugin-interface"
    interface.mkdir(parents=True)
    src = ROOT / "shared/plugin-interface"
    for name in ("pyproject.toml", "README.md", "LICENSE.md", "LICENSE"):
        if (src / name).exists():
            shutil.copy2(src / name, interface / name)
    shutil.copytree(src / "src", interface / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"))
    _git(interface, "init", "-q")
    _git(interface, "add", ".")
    _git(interface, "commit", "-q", "-m", "interface")
    for target in TARGETS:
        (root / target).mkdir(parents=True)
        (root / target / "pyproject.toml").write_text(_pyproject(Path(target).name))
    plugin = tmp_path / "aisc-plugin-example"
    plugin.mkdir()
    (plugin / "pyproject.toml").write_text(_pyproject("aisc-plugin-example"))
    return root, plugin


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", f"scripts/{SCRIPT.name}", *args], cwd=root, capture_output=True,
                          text=True, timeout=900, env={**os.environ})


def _vendor_dirs(*repos: Path) -> list[str]:
    return [str(r / "vendor") for r in repos if (r / "vendor").exists()]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_lock_takes_vendored(repo: Path) -> None:
    lock = tomllib.loads((repo / "uv.lock").read_text())
    entries = [p for p in lock.get("package", []) if p.get("name") == "aisc-plugin-interface"]
    assert len(entries) == 1, f"{repo}/uv.lock: {entries}"
    (entry,) = entries
    assert entry["version"] == "0.4.0"
    assert entry["source"] == {"path": f"vendor/{WHEEL}"}
    assert entry["wheels"][0]["hash"] == "sha256:" + _sha256(repo / "vendor" / WHEEL)


def test_a_dirty_interface_is_refused(scratch):
    root, plugin = scratch
    init = root / "shared/plugin-interface/src/aisc_plugin_interface/__init__.py"
    init.write_text(init.read_text() + "\n# an uncommitted change\n")
    r = _run(root)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "shared/plugin-interface has uncommitted changes" in r.stderr
    assert not _vendor_dirs(*(root / t for t in TARGETS), plugin)


def test_a_target_not_pointing_at_the_wheel_is_refused_before_anything_is_written(scratch):
    root, plugin = scratch
    (root / "apps/eval/pyproject.toml").write_text(_pyproject("eval", with_source=False))
    r = _run(root)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "apps/eval/pyproject.toml" in r.stderr
    assert f"vendor/{WHEEL}" in r.stderr
    assert not (root / "apps/backend/vendor").exists()
    assert not (root / "apps/eval/vendor").exists()


def test_a_plugin_repo_without_pyproject_is_refused(scratch, tmp_path):
    root, plugin = scratch
    empty = tmp_path / "empty-plugin"
    empty.mkdir()
    r = _run(root, str(plugin), str(empty))
    assert r.returncode == 1, r.stdout + r.stderr
    assert f"{empty} has no pyproject.toml" in r.stderr
    assert not _vendor_dirs(*(root / t for t in TARGETS), plugin, empty)


def _vendor_all(root: Path, plugin: Path) -> subprocess.CompletedProcess:
    r = _run(root, str(plugin))
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def test_it_vendors_and_locks_every_target(scratch):
    root, plugin = scratch
    r = _vendor_all(root, plugin)
    named = [m.group(1) for line in r.stdout.splitlines() if (m := VENDORED.match(line))]
    assert len(named) == 4, r.stdout
    for said, expected in zip(named, [*TARGETS, plugin.name]):
        assert said.rstrip("/").endswith(expected), f"{said!r} is not {expected}"
    repos = [*(root / t for t in TARGETS), plugin]
    for repo in repos:
        _assert_lock_takes_vendored(repo)
    assert len({_sha256(repo / "vendor" / WHEEL) for repo in repos}) == 1


def test_a_second_run_changes_nothing(scratch):
    root, plugin = scratch
    repos = [*(root / t for t in TARGETS), plugin]
    _vendor_all(root, plugin)
    first = {repo: ((repo / "vendor" / WHEEL).read_bytes(), (repo / "uv.lock").read_bytes()) for repo in repos}
    stale = [repo / "vendor/aisc_plugin_interface-0.3.9-py3-none-any.whl" for repo in repos]
    for path in stale:
        path.write_bytes(b"an older wheel")
    _vendor_all(root, plugin)
    for repo in repos:
        assert (repo / "vendor" / WHEEL).read_bytes() == first[repo][0], f"{repo}: the wheel changed"
        assert (repo / "uv.lock").read_bytes() == first[repo][1], f"{repo}: the lock changed"
    assert not [str(p) for p in stale if p.exists()]
