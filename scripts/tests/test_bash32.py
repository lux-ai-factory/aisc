"""The scripts a participant runs work on macOS's bash, 3.2 (secrets.sh once stopped there at
`declare -A`, which needs bash 4). Two checks: no bash-4-only syntax anywhere in scripts/, and
secrets.sh and start.sh really run under bash 3.2.57 (the docker image bash:3.2, the version macOS
ships), on a scratch copy, with uv running scripts/aisc.py as on a Mac. The real-bash checks need docker
and are skipped without it."""
import os
import re
import shutil
import subprocess

import pytest

from conftest import ROOT, add_fake_kcadm, copy_install_scripts
from test_start_script import DOCKER, GIT, sign_in_page

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


def bash32(workdir, script, image, *, setup="", env=None):
    """Run `script` under bash 3.2.57 in `image` (bash:3.2 with Python and uv), in `workdir` (mounted at /w).
    The host's network, so a stand-in page on the host's 127.0.0.1 answers it."""
    flags = []
    for k, v in {"UV_CACHE_DIR": "/w/.uv-cache", **(env or {})}.items():
        flags += ["-e", f"{k}={v}"]
    cmd = (f"{setup} cd /w && bash --version | head -1 && bash {script}")
    return subprocess.run(["docker", "run", "--rm", "--network", "host", "-u", f"{os.getuid()}:{os.getgid()}",
                           "-v", f"{workdir}:/w", *flags, image, "sh", "-c", cmd],
                          capture_output=True, text=True, timeout=300)


@pytest.fixture(scope="module")
def tools_image():
    """bash:3.2 with what the install scripts need on a Mac: Python and uv, which runs scripts/aisc.py. Built once."""
    tag = "aisc-test-bash32:latest"
    dockerfile = ("FROM bash:3.2\nRUN apk add --no-cache python3\n"
                  "COPY --from=ghcr.io/astral-sh/uv:0.11.15 /uv /usr/local/bin/uv\n")
    r = subprocess.run(["docker", "build", "-q", "-t", tag, "-"], input=dockerfile,
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
        copy_install_scripts(d)
        shutil.copy(ROOT / "keycloak/aisc-realm.json", d / "keycloak/aisc-realm.json")
        shutil.copy(ROOT / "env.plugin_downloader", d / "env.plugin_downloader")
        if shell == "bash32":
            r = bash32(d, "scripts/secrets.sh && bash scripts/secrets.sh --rotate", tools_image)
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
def test_start_sh_runs_under_bash_3_2(tmp_path, tools_image):
    copy_install_scripts(tmp_path)
    shutil.copy(ROOT / "env.plugin_downloader", tmp_path / "env.plugin_downloader")
    page = sign_in_page(tmp_path)
    shims = tmp_path / "shims"
    shims.mkdir()
    for name, body in (("docker", DOCKER), ("git", GIT)):
        (shims / name).write_text(body)
        (shims / name).chmod(0o755)
    add_fake_kcadm(shims)
    (tmp_path / "branch").write_text("feat/unified-modules\n")
    (tmp_path / "submodules").write_text(" 1a2b3c apps/backend (heads/feat/unified-modules)\n")
    (tmp_path / "compose-version").write_text("5.5.1\n")
    (tmp_path / "build-failures").write_text("1")
    r = bash32(tmp_path, "scripts/start.sh", tools_image,
               env={"PATH": "/w/shims:/usr/local/bin:/usr/bin:/bin", "START_WAIT_S": "6", "START_POLL_S": "0",
                    "START_MIN_DISK_GB": "0", "START_URL": f"http://127.0.0.1:{page.server_address[1]}/",
                    "START_SIGN_IN_URL": f"http://127.0.0.1:{page.server_address[1]}/realms/aisc"})
    page.shutdown()
    assert "version 3.2" in r.stdout, r.stdout + r.stderr
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
    assert "AISC is up" in r.stdout
