"""One way for the tests to resolve the stack's compose files.

`docker compose config` on copies of the files, with the settings file the stack itself reads
(env.plugin_downloader, which scripts/secrets.sh turns into env.runtime) and a dummy value for every
secret the files demand (`${NAME:?...}`). Read-only: nothing is started, stopped or built, and
env.secrets is never read.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from conftest import ROOT

#: the files scripts/start.sh starts the stack with, but the plugin downloader's
FILES = ["docker-compose-infra.development.yml", "docker-compose.development.yml"]
SETTINGS = ROOT / "env.plugin_downloader"


def _source(f) -> Path:
    """A file named relative to the checkout, or given as a path (such as an older version of one)."""
    return f if isinstance(f, Path) else ROOT / f


def required(files=FILES) -> set[str]:
    """The secrets the files demand: every `${NAME:?...}`."""
    return {n for f in files for n in re.findall(r"\$\{([A-Z0-9_]+):\?", _source(f).read_text())}


def run(tmp_path: Path, *profiles: str, files=FILES, env: dict | None = None, drop: tuple = (),
        settings: str = "", settings_file: Path | None = SETTINGS, quiet: bool = False,
        missing: tuple = (), project: str = "aisc-t-config") -> subprocess.CompletedProcess:
    """`docker compose config` (`-q` when quiet, otherwise JSON) on copies of `files` in tmp_path.

    files: names relative to the checkout, or paths (outside tmp_path's top level).
    profiles: compose profiles to turn on. env: values over the dummy secrets. drop: prefixes of the
    caller's environment variables to leave out, so a value set on the host cannot mask the files'.
    missing: names given neither a dummy nor the host's value, to see compose refuse them.
    settings: lines added to a copy of the settings file. settings_file: None for none at all (the
    standalone engine, which the stack's settings file is not for)."""
    args = []
    for f in files:
        shutil.copy(_source(f), tmp_path / Path(f).name)
        args += ["-f", str(tmp_path / Path(f).name)]
    if settings:
        base = settings_file.read_text() if settings_file else ""
        settings_file = tmp_path / "settings.env"
        settings_file.write_text(base + "\n" + settings)
    environ = {k: v for k, v in os.environ.items() if not (drop and k.startswith(drop)) and k not in missing}
    environ.update({k: "dummy" for k in required(files) if k not in missing})
    environ.update(env or {})
    prof = [a for p in profiles for a in ("--profile", p)]
    env_file = ["--env-file", str(settings_file)] if settings_file else []
    cmd = ["docker", "compose", "-p", project, "--project-directory", str(ROOT), *env_file,
           *prof, *args, "config"] + (["-q"] if quiet else ["--format", "json"])
    return subprocess.run(cmd, env=environ, capture_output=True, text=True)


def config(tmp_path: Path, *profiles: str, **kw) -> dict:
    """The resolved configuration; fails the test with compose's own message when it does not resolve."""
    r = run(tmp_path, *profiles, **kw)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)
