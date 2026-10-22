"""How scripts/secrets.sh protects the secrets it writes.

- Every file it writes is private from the moment it exists (umask 077 first), not only after a
  later chmod.
- A secret with an empty value (an earlier run left NAME=) is treated as missing and generated again.
- Every file is written beside the old one and moved into place, so a run that fails (here: a folder
  it cannot write in, as on a full disk) leaves the old files as they were and no temporary file.
- PLATFORM_SECRETS_KEY survives `--rotate` (it encrypts every stored LLM key).

secrets.sh runs on a scratch copy; nothing in the repo is written, nothing is started, and no value
is printed here.

    uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_secrets_hardening.py
"""

import contextlib
import hashlib
import json
import os
import re
import stat
import subprocess

import pytest

from conftest import ROOT, aisc_py
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
    install, and a run on an existing env.secrets."""
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


@contextlib.contextmanager
def _read_only(d):
    """A folder the run cannot write in: every file it would write fails, as on a full disk."""
    d.chmod(0o555)
    try:
        yield
    finally:
        d.chmod(0o755)


def test_a_new_install_that_cannot_write_stops_and_leaves_nothing(scratch):  # noqa: F811
    with _read_only(scratch):
        r = _run(scratch)
    assert r.returncode != 0, "the script went on without its files"
    assert "as they were" in r.stderr and "Traceback" not in r.stderr, r.stderr[-1000:]
    assert not (scratch / "env.secrets").exists() and not (scratch / "env.runtime").exists()


def test_a_failed_rotate_leaves_the_old_file_as_it_was(scratch):  # noqa: F811
    run_secrets(scratch)
    before = (scratch / "env.secrets").read_text()
    with _read_only(scratch):
        r = _run(scratch, "--rotate")
    assert r.returncode != 0
    assert _digest((scratch / "env.secrets").read_text()) == _digest(before), "a failed rotation changed env.secrets"
    assert [p.name for p in scratch.iterdir() if p.name.startswith("env.secrets.")] == [], "temp file left"


# The ledger's secrets. Its master keys are
# versioned and kept for ever, so `--rotate` must not replace them (a new version is added by
# `--add-ledger-key`); the immudb user's password changes only together with immudb's own copy.
LEDGER_KEPT = ("PLATFORM_LEDGER_KEYS", "LEDGER_IMMUDB_PASSWORD")


def test_the_ledger_secrets_are_made_with_their_shapes(scratch):  # noqa: F811
    run_secrets(scratch)
    values = secrets_of(scratch)
    assert re.fullmatch(r"v1:[0-9a-f]{64}", values["PLATFORM_LEDGER_KEYS"]), "PLATFORM_LEDGER_KEYS is v1:<64 hex>"
    assert _immudb_strong(values["LEDGER_IMMUDB_PASSWORD"])


def test_the_ledger_secrets_survive_rotate(scratch):  # noqa: F811
    run_secrets(scratch)
    before = secrets_of(scratch)
    r = _run(scratch, "--rotate")
    assert r.returncode == 0, r.stderr[-2000:]
    after = secrets_of(scratch)
    for name in LEDGER_KEPT:
        assert _digest(after[name]) == _digest(before[name]), f"{name} was rotated"


def test_a_ledger_key_version_is_added_never_replaced(scratch):  # noqa: F811
    run_secrets(scratch)
    before = secrets_of(scratch)["PLATFORM_LEDGER_KEYS"]
    r = _run(scratch, "--add-ledger-key")
    assert r.returncode == 0, r.stderr[-2000:]
    after = secrets_of(scratch)["PLATFORM_LEDGER_KEYS"]
    assert after.startswith(before + ",v2:") and re.fullmatch(r"v1:[0-9a-f]{64},v2:[0-9a-f]{64}", after)
    others_before = {k: _digest(v) for k, v in secrets_of(scratch).items() if k != "PLATFORM_LEDGER_KEYS"}
    assert others_before                                           # nothing else changed is checked below
    r = _run(scratch, "--add-ledger-key")
    assert re.fullmatch(r"v1:[0-9a-f]{64},v2:[0-9a-f]{64},v3:[0-9a-f]{64}", secrets_of(scratch)["PLATFORM_LEDGER_KEYS"])
    assert {k: _digest(v) for k, v in secrets_of(scratch).items() if k != "PLATFORM_LEDGER_KEYS"} == others_before


def test_an_added_ledger_key_reaches_env_runtime(scratch):  # noqa: F811
    """Compose reads env.runtime, so the new version must be there too."""
    run_secrets(scratch)
    r = _run(scratch, "--add-ledger-key")
    assert r.returncode == 0, r.stderr[-2000:]
    runtime = (scratch / "env.runtime").read_text()
    keys = secrets_of(scratch)["PLATFORM_LEDGER_KEYS"]
    assert f"PLATFORM_LEDGER_KEYS={keys}" in runtime and ",v2:" in keys


def test_a_malformed_ledger_key_list_is_refused_and_nothing_changes(scratch):  # noqa: F811
    run_secrets(scratch)
    out = scratch / "env.secrets"
    text = out.read_text().replace(secrets_of(scratch)["PLATFORM_LEDGER_KEYS"], "v1:notakey")
    out.write_text(text)
    r = _run(scratch, "--add-ledger-key")
    assert r.returncode != 0 and "PLATFORM_LEDGER_KEYS" in r.stderr
    assert out.read_text() == text
    assert not list(scratch.glob("env.secrets.*")), "a temporary file was left behind"



def _immudb_strong(value):
    """immudb refuses a password without an upper and a lower case letter, a digit and a symbol, or
    shorter than 8 or longer than 32 characters (it would refuse the ledger user, and the superuser)."""
    return all([8 <= len(value) <= 32, re.search(r"[A-Z]", value), re.search(r"[a-z]", value),
                re.search(r"[0-9]", value), re.search(r"[^A-Za-z0-9]", value)])


def test_the_immudb_superuser_password_is_generated_and_strong(scratch):  # noqa: F811
    """It lives in env.secrets, never in a tracked file."""
    run_secrets(scratch)
    values = secrets_of(scratch)
    assert _immudb_strong(values["IMMUDB_ADMIN_PASSWORD"])
    assert values["IMMUDB_ADMIN_PASSWORD"] != "immudbDev1!"


def test_the_superuser_password_rotates_but_the_ledger_users_does_not(scratch):  # noqa: F811
    """immudb re-applies the superuser's password at every start (IMMUDB_FORCE_ADMIN_PASSWORD), so
    --rotate may change it; aisc_ledger's lives inside immudb and is kept."""
    run_secrets(scratch)
    before = secrets_of(scratch)
    assert _run(scratch, "--rotate").returncode == 0
    after = secrets_of(scratch)
    assert _digest(after["IMMUDB_ADMIN_PASSWORD"]) != _digest(before["IMMUDB_ADMIN_PASSWORD"])
    assert _digest(after["LEDGER_IMMUDB_PASSWORD"]) == _digest(before["LEDGER_IMMUDB_PASSWORD"])


def test_the_immudb_signing_key_is_made_private_and_kept(scratch):  # noqa: F811
    """immudb signs its states with it; the platform checks them with the public
    half. A new key would make every saved state unverifiable, so --rotate keeps it."""
    run_secrets(scratch)
    key, pub = scratch / "immudb-signing.key", scratch / "immudb-signing.pub"
    assert key.exists() and pub.exists()
    assert "PRIVATE KEY" in key.read_text() and "PUBLIC KEY" in pub.read_text()
    assert _mode(key) & 0o007 == 0, "the private key must not be readable by others"
    acl = subprocess.run(["getfacl", "-cp", str(key)], capture_output=True, text=True).stdout
    if acl:                                            # with an ACL the group bits show its mask
        entries = dict(line.split(":", 1)[::-1] and (line.rsplit(":", 1)[0], line.rsplit(":", 1)[1])
                       for line in acl.splitlines() if line and not line.startswith("#"))
        assert entries.get("group:") == "---", "the owning group must not read the private key"
        # no grant for immudb's uid: the stack's immudb-key job hands it a copy (test_no_host_network)
        assert "user:3322" not in entries, "no file ACL any more"
    else:
        assert _mode(key) & 0o070 == 0, "the private key must not be readable by its group"
    before = _digest(key.read_text())
    assert _run(scratch, "--rotate").returncode == 0
    assert _digest(key.read_text()) == before


def _generated_names():
    """Every NAME of the install script's SECRETS list: the secrets it generates into env.secrets."""
    return [name for name, _ in aisc_py().SECRETS]


@pytest.mark.parametrize("name", ["env.plugin_downloader", "env.staging"])
def test_no_tracked_env_file_sets_a_generated_secret(name):
    """A generated secret lives in env.secrets only; a tracked env file that set one would give every
    install the same value."""
    names = _generated_names()
    assert {"DASHBOARD_BRIDGE_TOKEN", "PLATFORM_SECRETS_KEY", "QUALIFICATION_WEB_TO_AGENTS_TOKEN"} <= set(names), names
    text = (ROOT / name).read_text()
    set_here = [n for n in names if n not in STILL_TRACKED and re.search(rf"^{n}=", text, re.M)]
    assert not set_here, f"{name} sets {set_here}"


# The infrastructure passwords secrets.sh now generates are still set on lines other teams maintain
# (env.plugin_downloader, and env.staging, which secrets.sh does not build), so they are not deleted
# yet. env.runtime drops the tracked values and takes
# env.secrets' (test_infra_passwords.py). Delete the lines, then this set.
STILL_TRACKED = {"POSTGRES_PASSWORD", "S3_PASSWORD", "RABBITMQ_PASSWORD", "KEYCLOAK_ADMIN_PASSWORD"}


def test_rotate_keeps_what_stored_data_needs_and_names_real_steps(scratch):  # noqa: F811
    """Devpi refuses to start when its volume's root password is not DEVPI_ROOT_PASSWORD,
    and Superset's SECRET_KEY encrypts the stored database connections; --rotate keeps both. The
    header names no `make` target (there is no Makefile)."""
    run_secrets(scratch)
    before = secrets_of(scratch)
    assert _run(scratch, "--rotate").returncode == 0
    after = secrets_of(scratch)
    for name in ("DEVPI_ROOT_PASSWORD", "SUPERSET_SECRET_KEY"):
        assert _digest(after[name]) == _digest(before[name]), f"--rotate replaced {name}"
    header = [line for line in (scratch / "env.secrets").read_text().splitlines() if line.startswith("#")]
    assert not any(re.search(r"\bmake\b", line) for line in header), header
    assert not (ROOT / "Makefile").exists()


# The engine's own immudb user, aisc_engine. ledger-pool creates it in
# immudb with this password, so like LEDGER_IMMUDB_PASSWORD it survives --rotate.


def test_a_new_install_gets_a_strong_engine_immudb_password_of_its_own(scratch):  # noqa: F811
    r = run_secrets(scratch)
    values = secrets_of(scratch)
    assert "ENGINE_IMMUDB_PASSWORD" in set(values), "secrets.sh does not generate ENGINE_IMMUDB_PASSWORD"
    engine = values["ENGINE_IMMUDB_PASSWORD"]
    strong = bool(_immudb_strong(engine))                       # booleans only: a failure prints no value
    assert strong, "ENGINE_IMMUDB_PASSWORD does not meet immudb's rules"
    distinct = engine not in (values["IMMUDB_ADMIN_PASSWORD"], values["LEDGER_IMMUDB_PASSWORD"])
    assert distinct, "ENGINE_IMMUDB_PASSWORD equals another immudb password"
    printed = engine in r.stdout + r.stderr
    assert not printed, "the value was printed"


def test_an_existing_install_gains_it_and_keeps_every_other_value(scratch):  # noqa: F811
    run_secrets(scratch)
    out = scratch / "env.secrets"
    lines = [line for line in out.read_text().splitlines() if not line.startswith("ENGINE_IMMUDB_PASSWORD=")]
    out.write_text("\n".join(lines) + "\n")                     # an env.secrets made before the name existed
    before = secrets_of(scratch)
    r = run_secrets(scratch)
    after = secrets_of(scratch)
    assert "ENGINE_IMMUDB_PASSWORD" in set(after), "a plain run did not add ENGINE_IMMUDB_PASSWORD"
    strong = bool(_immudb_strong(after["ENGINE_IMMUDB_PASSWORD"]))
    assert strong, "ENGINE_IMMUDB_PASSWORD does not meet immudb's rules"
    others_after = _digest({k: v for k, v in after.items() if k != "ENGINE_IMMUDB_PASSWORD"})
    assert others_after == _digest(before), "another value changed"
    runtime = dict(line.split("=", 1) for line in (scratch / "env.runtime").read_text().splitlines()
                   if "=" in line and not line.startswith("#"))
    carried = runtime.get("ENGINE_IMMUDB_PASSWORD") == after["ENGINE_IMMUDB_PASSWORD"]
    assert carried, "env.runtime does not carry it"
    printed = after["ENGINE_IMMUDB_PASSWORD"] in r.stdout + r.stderr
    assert not printed, "the value was printed"


def test_rotate_keeps_the_engine_immudb_password_and_still_rotates_the_superusers(scratch):  # noqa: F811
    run_secrets(scratch)
    before = secrets_of(scratch)
    assert "ENGINE_IMMUDB_PASSWORD" in set(before), "secrets.sh does not generate ENGINE_IMMUDB_PASSWORD"
    assert _run(scratch, "--rotate").returncode == 0
    after = secrets_of(scratch)
    kept = after["ENGINE_IMMUDB_PASSWORD"] == before["ENGINE_IMMUDB_PASSWORD"]
    assert kept, "--rotate replaced ENGINE_IMMUDB_PASSWORD"
    rotated = after["IMMUDB_ADMIN_PASSWORD"] != before["IMMUDB_ADMIN_PASSWORD"]
    assert rotated, "--rotate no longer rotates IMMUDB_ADMIN_PASSWORD"
