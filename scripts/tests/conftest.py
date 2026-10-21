"""Shared helpers for the tests of the repo's scripts, compose files, Caddyfile and pages.

Run from the repo root:

    uv run --no-project --with pytest --with pyyaml --with 'psycopg[binary]' \
        python -m pytest -q -p no:cacheprovider scripts/tests

Some start throwaway postgres:15-alpine containers (never the host's 5432), through
scripts/guard-frozen.sh, scripts/test-pipeline-chain.sh and scripts/lib/; others read
`docker compose config` of scratch copies of the compose files (never up, down or build).
"""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts/guard-frozen.sh"
CHAIN = ROOT / "scripts/test-pipeline-chain.sh"


#: the install scripts: the bash wrappers, scripts/aisc.py they run, and the helper that runs it with uv
INSTALL_SCRIPTS = ("scripts/aisc.py", "scripts/secrets.sh", "scripts/start.sh", "scripts/rotate-infra-password.sh",
                   "scripts/lib/aisc-py.sh")


def copy_install_scripts(dest: Path) -> None:
    """The install scripts into a scratch copy of the repo, where they run as in a clone."""
    for path in INSTALL_SCRIPTS:
        (dest / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, dest / path)


def aisc_py(root: Path = ROOT):
    """scripts/aisc.py as a module: its list of secrets, the kind of value each takes, what --rotate keeps.
    root: a scratch copy of the checkout (copy_install_scripts) to load it from, so it reads that copy's files."""
    spec = importlib.util.spec_from_file_location("aisc_install", root / "scripts/aisc.py")
    module = importlib.util.module_from_spec(spec)
    # registered before it runs, as an import would: a dataclass looks its own module up while it is made
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)


def container_name(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("container: "):
            return line.split(": ", 1)[1].strip()
    raise AssertionError("the script did not print its container name:\n" + output[-2000:])


def container_exists(name: str) -> bool:
    r = run(["docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"])
    return name in r.stdout.split()


@pytest.fixture(scope="session")
def guard_all(tmp_path_factory):
    """One full guard run (checks G3 and G4; G1, G2 and G5 are retired), shared by the tests that read its
    verdict lines."""
    out = tmp_path_factory.mktemp("guard-all")
    r = run([str(GUARD)], env={**__import__("os").environ, "GUARD_OUT": str(out)}, timeout=900)
    return r, out



def submodule_missing(path: str) -> bool:
    folder = ROOT / path
    return not folder.is_dir() or not any(folder.iterdir())


def needs_submodule(path: str):
    return pytest.mark.skipif(submodule_missing(path), reason=f"{path} is a private repository, not checked out here")


#: The guard's references to earlier states of the code, by the repository they are commits of. They are in
#: the local history of the workstation that made them, not on GitHub, so a fresh clone (the CI's) lacks them.
GUARD_HISTORY = {"QUAL_REF": "apps/qualification", "ORDERS_ENGINE_REF": "apps/backend", "LIVE_ENGINE": "apps/backend",
                 "LIVE_TOP": ".", "ORDERS_TOP_REF": "."}


def guard_history_missing() -> list[str]:
    import re
    text = GUARD.read_text()
    missing = []
    for name, repo in GUARD_HISTORY.items():
        m = re.search(rf"^{name}=([0-9a-f]{{7,40}})\b", text, re.M)
        if m and subprocess.run(["git", "-C", str(ROOT / repo), "cat-file", "-e", m.group(1) + "^{commit}"],
                                capture_output=True).returncode != 0:
            missing.append(f"{name}={m.group(1)}")
    return missing


def needs_guard_history():
    missing = guard_history_missing()
    return pytest.mark.skipif(bool(missing), reason="the guard's earlier states are not in this checkout's history: "
                              + ", ".join(missing))


@pytest.fixture(scope="session")
def guard_orders(tmp_path_factory):
    missing = guard_history_missing()
    if missing:
        pytest.skip("the guard's earlier states are not in this checkout's history: " + ", ".join(missing))
    out = tmp_path_factory.mktemp("guard-orders")
    r = run([str(GUARD), "--orders"], env={**__import__("os").environ, "GUARD_OUT": str(out)}, timeout=1800)
    return r, out


def verdict(output: str, check: str) -> list[str]:
    return [line for line in output.splitlines() if line.startswith(check + " ")]
