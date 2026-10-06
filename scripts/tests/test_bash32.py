"""The scripts a participant runs work on macOS's bash, 3.2 (workshop 2026-10-06: secrets.sh stopped at
`declare -A`, which needs bash 4). Two checks: no bash-4-only syntax anywhere in scripts/, and
secrets.sh and start.sh really run under bash 3.2.57 (the docker image bash:3.2, the version macOS
ships), on a scratch copy. The real-bash checks need docker and are skipped without it."""
import os
import re
import shutil
import subprocess

import pytest

from conftest import ROOT
from test_start_script import CURL, DOCKER, GIT

#: Syntax bash 3.2 does not have: associative arrays, namerefs, mapfile/readarray, case modification,
#: |& and &>>, coproc.
BASH4 = [
    (r"\bdeclare\s+-[a-zA-Z]*A", "declare -A (associative array)"),
    (r"\b(declare|local)\s+-[a-zA-Z]*n\b", "nameref"),
    (r"\b(mapfile|readarray)\b", "mapfile/readarray"),
    (r"\$\{[A-Za-z_][A-Za-z0-9_]*(\[[^]]*\])?(,,?|\^\^?)\}", "case modification ${x,,} ${x^^}"),
    (r"\|&", "|&"),
    (r"&>>", "&>>"),
    (r"^\s*coproc\b", "coproc"),
]


def scripts():
    return sorted(p for p in (ROOT / "scripts").rglob("*.sh") if "tests" not in p.parts)


def test_no_script_uses_syntax_bash_3_2_lacks():
    found = []
    for path in scripts():
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for pattern, what in BASH4:
                if re.search(pattern, line):
                    found.append(f"{path.relative_to(ROOT)}:{n}: {what}")
    assert not found, "bash 4 only (macOS has bash 3.2):\n" + "\n".join(found)


def _docker():
    return shutil.which("docker") and subprocess.run(["docker", "info"], capture_output=True).returncode == 0


needs_docker = pytest.mark.skipif(not _docker(), reason="needs docker for the bash:3.2 image")


def bash32(workdir, script, *, setup="", env=None):
    """Run `script` under bash 3.2.57 in the bash:3.2 image, in `workdir` (mounted at /w)."""
    flags = []
    for k, v in (env or {}).items():
        flags += ["-e", f"{k}={v}"]
    cmd = (f"{setup} cd /w && bash --version | head -1 && bash {script}")
    return subprocess.run(["docker", "run", "--rm", "-u", f"{os.getuid()}:{os.getgid()}", "-v", f"{workdir}:/w",
                           *flags, "bash:3.2", "sh", "-c", cmd],
                          capture_output=True, text=True, timeout=300)


@pytest.fixture(scope="module")
def tools_image():
    """bash:3.2 with what secrets.sh calls (openssl, python3), built once."""
    tag = "aisc-test-bash32:latest"
    r = subprocess.run(["docker", "build", "-q", "-t", tag, "-"], input="FROM bash:3.2\nRUN apk add --no-cache openssl python3\n",
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr
    return tag


@needs_docker
def test_secrets_sh_runs_under_bash_3_2_and_makes_what_bash_5_makes(tmp_path, tools_image):
    names = {}
    for shell in ("bash32", "bash5"):
        d = tmp_path / shell
        (d / "scripts").mkdir(parents=True)
        (d / "keycloak").mkdir()
        shutil.copy(ROOT / "scripts/secrets.sh", d / "scripts/secrets.sh")
        shutil.copy(ROOT / "keycloak/aisc-realm.json", d / "keycloak/aisc-realm.json")
        shutil.copy(ROOT / "env.plugin_downloader", d / "env.plugin_downloader")
        if shell == "bash32":
            r = subprocess.run(["docker", "run", "--rm", "-u", f"{os.getuid()}:{os.getgid()}", "-v", f"{d}:/w",
                                tools_image, "sh", "-c", "cd /w && bash --version | head -1 && bash scripts/secrets.sh"
                                " && bash scripts/secrets.sh --rotate"],
                               capture_output=True, text=True, timeout=300)
            assert "version 3.2" in r.stdout, r.stdout
        else:
            r = subprocess.run(["bash", "-c", "bash scripts/secrets.sh && bash scripts/secrets.sh --rotate"], cwd=d,
                               capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
        lines = [line for line in (d / "env.secrets").read_text().splitlines() if line and not line.startswith("#")]
        assert all(line.split("=", 1)[1] for line in lines), "an empty secret"
        names[shell] = sorted(line.split("=", 1)[0] for line in lines)
        assert (d / "env.runtime").exists()
    assert names["bash32"] == names["bash5"]


@needs_docker
def test_start_sh_runs_under_bash_3_2(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/start.sh", tmp_path / "scripts/start.sh")
    (tmp_path / "scripts/secrets.sh").write_text("#!/bin/sh\n: > env.runtime\n")
    (tmp_path / "scripts/secrets.sh").chmod(0o755)
    shims = tmp_path / "shims"
    shims.mkdir()
    for name, body in (("docker", DOCKER), ("git", GIT), ("curl", CURL)):
        (shims / name).write_text(body)
        (shims / name).chmod(0o755)
    (tmp_path / "branch").write_text("feat/unified-modules\n")
    (tmp_path / "submodules").write_text(" 1a2b3c apps/backend (heads/feat/unified-modules)\n")
    (tmp_path / "compose-version").write_text("5.5.1\n")
    (tmp_path / "build-failures").write_text("1")
    r = bash32(tmp_path, "scripts/start.sh",
               env={"PATH": "/w/shims:/usr/local/bin:/usr/bin:/bin", "START_WAIT_S": "6", "START_POLL_S": "0",
                    "START_MIN_DISK_GB": "0"})
    assert "version 3.2" in r.stdout, r.stdout + r.stderr
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
    assert "AISC is up" in r.stdout
