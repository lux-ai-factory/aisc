"""scripts/secrets.sh hardening (final review of the engine adapt, 2026-09-28, T6d).

- Every file it writes is private from the moment it exists (`umask 077` first), not only after a
  later chmod.
- A secret with an empty value (openssl failed) is treated as missing and generated again; if a value
  is still empty the script stops rather than leave an install on an empty secret.
- `--rotate` builds the new env.secrets beside the old one and moves it into place, so a rotation
  that fails leaves the old file as it was.
- PLATFORM_SECRETS_KEY survives `--rotate` (it encrypts every stored LLM key).

secrets.sh runs on a scratch copy; nothing in the repo is written, nothing is started, and no value
is printed here.

    uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_secrets_hardening.py
"""

import hashlib
import json
import os
import re
import stat
import subprocess

from test_dashboard_bridge_token import scratch  # noqa: F401 (fixture)
from test_llm_keys import run_secrets, secrets_of


def _shim(d, name, body):
    bin_dir = d / "shims"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / name).write_text("#!/bin/sh\n" + body + "\n")
    (bin_dir / name).chmod(0o755)
    return {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}


def _run(d, *args, env=None):
    return subprocess.run(["bash", str(d / "scripts/secrets.sh"), *args], cwd=d, env=env,
                          capture_output=True, text=True, timeout=120)


def _digest(value):
    """What is compared instead of secret values, so a failing assertion prints no secret."""
    return hashlib.sha256(json.dumps(value, sort_keys=False).encode()).hexdigest()[:16]


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_platform_secrets_key_survives_rotate(scratch):  # noqa: F811
    run_secrets(scratch)
    before = secrets_of(scratch)
    r = _run(scratch, "--rotate")
    assert r.returncode == 0, r.stderr[-2000:]
    after = secrets_of(scratch)
    assert _digest(after["PLATFORM_SECRETS_KEY"]) == _digest(before["PLATFORM_SECRETS_KEY"]), "the key was rotated"
    assert _digest(after["DJANGO_SECRET_KEY"]) != _digest(before["DJANGO_SECRET_KEY"]), "--rotate rotated nothing"


def test_the_files_are_private_without_the_later_chmod(scratch):  # noqa: F811
    """chmod is made a no-op: what is left is what the files were created with. Both paths: a new
    install, and a run on an existing env.secrets (which used to create env.runtime world-readable)."""
    env = _shim(scratch, "chmod", "exit 0")
    for run in ("new", "existing"):
        if run == "existing":
            (scratch / "env.runtime").unlink()
        r = _run(scratch, env=env)
        assert r.returncode == 0, r.stderr[-2000:]
        for name in ("env.secrets", "env.runtime"):
            assert _mode(scratch / name) & 0o077 == 0, f"{run}: {name} was created readable by others"


def test_an_empty_value_is_generated_again_and_the_rest_kept(scratch):  # noqa: F811
    run_secrets(scratch)
    before = secrets_of(scratch)
    text = (scratch / "env.secrets").read_text()
    (scratch / "env.secrets").write_text(re.sub(r"^DJANGO_SECRET_KEY=.*$", "DJANGO_SECRET_KEY=", text, flags=re.M))
    r = run_secrets(scratch)
    after = secrets_of(scratch)
    assert re.fullmatch(r"[0-9a-f]{64}", after.get("DJANGO_SECRET_KEY", "")) is not None, "the empty value was kept"
    assert _digest({k: v for k, v in after.items() if k != "DJANGO_SECRET_KEY"}) == \
        _digest({k: v for k, v in before.items() if k != "DJANGO_SECRET_KEY"}), "another value changed"
    assert list(after) == list(before), "the order of env.secrets changed"
    assert after["DJANGO_SECRET_KEY"] not in r.stdout + r.stderr, "the new value was printed"


def test_a_new_install_stops_when_openssl_fails(scratch):  # noqa: F811
    env = _shim(scratch, "openssl", "exit 1")
    r = _run(scratch, env=env)
    assert r.returncode != 0, "secrets.sh went on with empty secrets"
    assert "empty" in r.stderr
    assert not (scratch / "env.runtime").exists(), "env.runtime was written from empty secrets"


def test_a_failed_rotate_leaves_the_old_file_as_it_was(scratch):  # noqa: F811
    run_secrets(scratch)
    before = (scratch / "env.secrets").read_text()
    env = _shim(scratch, "openssl", "exit 1")
    r = _run(scratch, "--rotate", env=env)
    assert r.returncode != 0
    assert _digest((scratch / "env.secrets").read_text()) == _digest(before), "a failed rotation changed env.secrets"
    assert [p.name for p in scratch.iterdir() if p.name.startswith("env.secrets.")] == [], "temp file left"
