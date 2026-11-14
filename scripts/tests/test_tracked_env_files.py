"""No tracked env file of ours holds a literal secret or a URL with a password in it.

Every tracked file named like an env file, in the root and in every submodule, is read: a line whose name
looks like a secret (PASSWORD, SECRET, TOKEN, ..._KEY) has an empty value or a reference ($NAME), and no
value holds a URL with a password between `:` and `@` unless the password is a reference or a <placeholder>.
The two env files the upstream engine authors are not ours to change: they are allowed only while none of
our compose files reads them.

Read-only: `git ls-files` and the files' text. A failure names the variable and the line, never the value.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT

SECRET_NAME = re.compile(r"PASSWORD|SECRET|TOKEN|_KEY$")
USERINFO = re.compile(r"://[^/\s:@$]+:(?!\$|<)[^@\s]+@")
ENV_NAME = re.compile(r"(^|/)(env\.[^/]*|[^/]*\.env|\.env[^/]*)$")
COMPOSE_FILES = ("docker-compose.development.yml", "docker-compose-infra.development.yml")

#: env files the upstream engine authors and keeps; listed for upstream, never read by our stack
UPSTREAM_ENV_FILES = {
    "apps/backend/env.development": "the upstream engine's development settings",
    "apps/eval/env.development": "the upstream worker's development settings",
}


def _submodules() -> list[str]:
    out = subprocess.run(["git", "submodule", "status"], cwd=ROOT, capture_output=True, text=True).stdout
    return [line.split()[1] for line in out.splitlines() if line.strip()]


def tracked_env_files() -> list[str]:
    found = []
    for prefix in ["", *_submodules()]:
        folder = ROOT / prefix if prefix else ROOT
        if not (folder / ".git").exists():
            continue
        names = subprocess.run(["git", "ls-files"], cwd=folder, capture_output=True, text=True).stdout.split("\n")
        for name in names:
            if name and ENV_NAME.search(name) and not name.endswith(".py"):
                found.append(f"{prefix}/{name}" if prefix else name)
    return sorted(found)


def _offending_lines(path: Path) -> list[str]:
    bad = []
    for n, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        name, eq, value = line.partition("=")
        if not eq:
            continue
        name = name.strip().removeprefix("export ").strip()
        value = value.strip().strip("'\"")
        if (SECRET_NAME.search(name) and value and not value.startswith("$")) or USERINFO.search(value):
            bad.append(f"{name}:{n}")
    return bad


def test_the_env_files_found_include_the_known_ones():
    found = tracked_env_files()
    assert "env.plugin_downloader" in found and "apps/controls/.env.example" in found, found


@pytest.mark.parametrize("path", tracked_env_files(), ids=str)
def test_a_tracked_env_file_holds_no_literal_secret(path):
    if path in UPSTREAM_ENV_FILES:
        used = [f for f in COMPOSE_FILES if path in (ROOT / f).read_text()]
        assert not used, f"{path} is upstream's and must not feed our stack ({used})"
        return
    bad = _offending_lines(ROOT / path)
    assert not bad, f"{path} holds literal secrets at {bad}"
