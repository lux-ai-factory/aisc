"""scripts/ledger-anchor.sh keeps a copy of the signed ledger heads outside the stack, one file a day.

It runs the platform's anchor command in the platform container, writes the JSON to
~/aisc-ledger-anchors/<UTC date>.json (file 0600, folder 0700, never inside the repo), refuses to overwrite a
day already written, and, when a webhook is named, posts the same bytes; a failed post exits non-zero and
keeps the file. Here `docker` is a fake on PATH and HOME a temporary folder: nothing reaches a stack.

Run from the repo root:

    uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_ledger_anchor_script.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ledger-anchor.sh"
DOCUMENT = {"anchored_at": "2026-11-14T00:00:00+00:00",
            "heads": [{"log": "ledgerplatform", "project_pid": None, "tx": 3, "hash": "ab" * 32,
                       "signature_b64": "c2ln", "verified_at": "2026-11-14T00:00:00+00:00"}]}


@pytest.fixture
def bed(tmp_path):
    bin_dir, home = tmp_path / "bin", tmp_path / "home"
    bin_dir.mkdir()
    home.mkdir()
    fake = bin_dir / "docker"
    fake.write_text("#!/bin/sh\ncat <<'JSON'\n" + json.dumps(DOCUMENT) + "\nJSON\n")
    fake.chmod(0o755)
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(home)}
    return env, home


def run(env, *args):
    assert SCRIPT.exists(), "scripts/ledger-anchor.sh does not exist"
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=ROOT, env=env, capture_output=True, text=True,
                          timeout=60)


def todays_file(home):
    return home / "aisc-ledger-anchors" / f"{dt.datetime.now(dt.timezone.utc).date().isoformat()}.json"


def test_writes_outside_the_repo_with_private_mode(bed):
    env, home = bed
    done = run(env)
    assert done.returncode == 0, done.stderr
    written = todays_file(home)
    assert json.loads(written.read_text()) == DOCUMENT
    assert stat.S_IMODE(written.stat().st_mode) == 0o600
    assert stat.S_IMODE(written.parent.stat().st_mode) == 0o700
    assert ROOT not in written.resolve().parents


def test_refuses_to_overwrite_a_day(bed):
    env, home = bed
    assert run(env).returncode == 0
    todays_file(home).write_text("kept")
    again = run(env)
    assert again.returncode != 0
    assert todays_file(home).read_text() == "kept"


def test_webhook_failure_exits_nonzero_and_keeps_the_file(bed):
    env, home = bed
    failed = run(env, "--webhook", "http://127.0.0.1:9/unreachable")
    assert failed.returncode != 0
    assert json.loads(todays_file(home).read_text()) == DOCUMENT
