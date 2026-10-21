"""plugin-publisher's command, run with stub `python -m build` and `twine`.

A plugin that does not build is named and the one-shot exits non-zero after uploading the rest, so
`docker compose ps -a` (and start.sh's list of what is down) shows it; with nothing built, twine is
not called on a literal `*`. Its comment says what twine does: every start uploads again.
"""
import os
import re
import subprocess

import yaml

from conftest import ROOT

DEV = ROOT / "docker-compose.development.yml"


def _service():
    return yaml.safe_load(DEV.read_text())["services"]["plugin-publisher"]


def _run(tmp_path, plugins):
    src, interface, out, bin_dir = (tmp_path / n for n in ("src", "interface", "out", "bin"))
    for d in (src, interface, out, bin_dir):
        d.mkdir()
    for name in plugins:
        (src / name).mkdir()
        (src / name / "pyproject.toml").write_text("")
    log = tmp_path / "twine.log"
    # python -m build --outdir OUT DIR: a directory named broken-* does not build
    (bin_dir / "python").write_text('#!/bin/sh\ncase "$5" in *broken-*) echo boom; exit 1;; esac\n'
                                    'touch "$4/$(basename "$5").whl"\n')
    (bin_dir / "twine").write_text(f'#!/bin/sh\necho "$@" >> {log}\n')
    (bin_dir / "mktemp").write_text(f"#!/bin/sh\necho {out}\n")
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    command = _service()["command"][0].replace("$$", "$").replace("/src/", f"{src}/").replace("/interface/", f"{interface}/")
    command = command.replace("/tmp/build.log", str(tmp_path / "build.log"))
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    r = subprocess.run(["sh", "-c", command], env=env, capture_output=True, text=True, timeout=60)
    return r, (log.read_text().splitlines() if log.exists() else [])


def test_a_plugin_that_does_not_build_fails_the_one_shot_after_the_rest_are_uploaded(tmp_path):
    r, calls = _run(tmp_path, ["good-a", "broken-b"])
    assert r.returncode != 0, r.stdout
    assert "broken-b" in r.stdout
    assert len(calls) == 1 and "good-a.whl" in calls[0] and "*" not in calls[0], calls


def test_with_nothing_built_twine_is_not_called_on_a_literal_star(tmp_path):
    r, calls = _run(tmp_path, ["broken-a"])
    assert r.returncode != 0
    assert calls == []


def test_every_plugin_built_exits_zero(tmp_path):
    r, calls = _run(tmp_path, ["good-a", "good-b"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(calls) == 1 and "good-a.whl" in calls[0] and "good-b.whl" in calls[0]


def test_the_comment_says_what_twine_does():
    text = DEV.read_text()
    block = re.search(r"((?:  #.*\n)+)  plugin-publisher:", text).group(1)
    assert "twine skips" not in block and "republishes nothing" not in block
    assert "--skip-existing" not in _service()["command"][0]
