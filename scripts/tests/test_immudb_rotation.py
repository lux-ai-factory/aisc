"""Rotating one of immudb's passwords.

`scripts/secrets.sh --rotate-one NAME` replaces exactly one of IMMUDB_ADMIN_PASSWORD, LEDGER_IMMUDB_PASSWORD
and ENGINE_IMMUDB_PASSWORD and leaves every other line alone; the restart of immudb, ledger-pool, platform
and aisc-backend then finishes the rotation (proven in platform/tests/ledger/test_ledger_rotation.py).

secrets.sh runs on a scratch copy of the repo's files in a temp dir; the real env.secrets and env.runtime
are never read or written, and no value is printed: values are compared by digest.
"""
from __future__ import annotations

import re

import pytest

from conftest import ROOT, aisc_py
from test_dashboard_bridge_token import scratch  # noqa: F401 (fixture)
from test_llm_keys import run_secrets, secrets_of
from test_secrets_hardening import _digest, _immudb_strong, _run

ROTATABLE = ("IMMUDB_ADMIN_PASSWORD", "LEDGER_IMMUDB_PASSWORD", "ENGINE_IMMUDB_PASSWORD")
RESTART = ("immudb", "ledger-pool", "platform", "aisc-backend")


def _lines(path):
    return path.read_text().splitlines()


def _files(d):
    return _digest((d / "env.secrets").read_text()), _digest((d / "env.runtime").read_text())


def _no_temp_left(d):
    assert not [p.name for p in d.iterdir() if re.match(r"env\.(secrets|runtime)\.", p.name)], "temporary file left"



@pytest.mark.parametrize("name", ROTATABLE)
def test_rotate_one_replaces_exactly_that_value(scratch, name):  # noqa: F811
    run_secrets(scratch)
    before = secrets_of(scratch)
    assert name in set(before), f"secrets.sh does not generate {name}"
    lines_before = _lines(scratch / "env.secrets")
    runtime_before = _lines(scratch / "env.runtime")
    r = _run(scratch, "--rotate-one", name)
    assert r.returncode == 0, r.stderr[-2000:]
    after = secrets_of(scratch)
    old_digest, new_digest = _digest(before[name]), _digest(after[name])   # never a value in a failure
    assert old_digest != new_digest, f"{name} was not rotated"
    assert _immudb_strong(after[name]), f"{name} does not meet immudb's rules"
    lines_after = _lines(scratch / "env.secrets")
    assert len(lines_after) == len(lines_before)
    changed = [i for i, (a, b) in enumerate(zip(lines_before, lines_after)) if a != b]
    ok = len(changed) == 1 and lines_after[changed[0]].startswith(name + "=")
    assert ok, f"{len(changed)} lines of env.secrets changed, want only {name}'s"
    runtime_after = _lines(scratch / "env.runtime")
    changed = [i for i, (a, b) in enumerate(zip(runtime_before, runtime_after)) if a != b]
    assert len(runtime_after) == len(runtime_before)
    ok = len(changed) == 1 and runtime_after[changed[0]] == f"{name}={after[name]}"
    assert ok, "env.runtime does not carry exactly the new value"
    printed = r.stdout + r.stderr
    leaked = before[name] in printed or after[name] in printed
    assert not leaked, "a value was printed"
    for service in RESTART:
        assert re.search(rf"\b{re.escape(service)}\b", printed), f"the output does not say to restart {service}"
    _no_temp_left(scratch)



@pytest.mark.parametrize("args", [("--rotate-one", "PLATFORM_SECRETS_KEY"), ("--rotate-one", "DJANGO_SECRET_KEY"),
                                  ("--rotate-one", "NO_SUCH_SECRET"), ("--rotate-one",)],
                         ids=["platform-secrets-key", "django-secret-key", "unknown", "no-name"])
def test_any_other_name_is_refused_and_nothing_changes(scratch, args):  # noqa: F811
    run_secrets(scratch)
    before = _files(scratch)
    r = _run(scratch, *args)
    assert r.returncode == 2, f"exit {r.returncode}"
    for name in ROTATABLE:
        assert name in r.stderr, f"the refusal does not name {name}"
    assert _files(scratch) == before
    _no_temp_left(scratch)



def test_without_env_secrets_it_writes_nothing(scratch):  # noqa: F811
    r = _run(scratch, "--rotate-one", "IMMUDB_ADMIN_PASSWORD")
    assert r.returncode != 0 and "scripts/secrets.sh" in r.stderr, r.stderr[-1000:]
    assert not (scratch / "env.secrets").exists() and not (scratch / "env.runtime").exists()



def test_a_failed_rotation_leaves_the_files_as_they_were(scratch):  # noqa: F811
    run_secrets(scratch)
    before = _files(scratch)
    scratch.chmod(0o555)                              # it cannot write: as on a full disk
    try:
        r = _run(scratch, "--rotate-one", "LEDGER_IMMUDB_PASSWORD")
    finally:
        scratch.chmod(0o755)
    assert r.returncode != 0, "the rotation went on without writing it"
    assert _files(scratch) == before
    _no_temp_left(scratch)


# The script header (only text exists)


def test_the_header_names_the_single_secret_rotation():
    assert "--rotate-one" in aisc_py().__doc__


# The guide (only text exists)


def test_the_guide_documents_the_rotation():
    flat = " ".join((ROOT / "docs/guide.md").read_text().split())
    i = flat.find("--rotate-one")
    assert i >= 0, "docs/guide.md does not document --rotate-one"
    near = flat[max(0, i - 600): i + 900]
    for service in RESTART:
        assert service in near, f"the rotation procedure does not restart {service}"


# Found in a rehearsal: `up -d immudb ledger-pool platform aisc-backend` recreates immudb but
# leaves an aisc-backend whose configuration did not change running, on a login immudb has ended ("invalid
# token"; its clerk now logs in again on the next write). After ledger-pool exits 0 the procedure still
# restarts aisc-backend, whichever of the three names was rotated, so the engine starts on the new password.

_RESTART_ENGINE = re.compile(r"restart\s+aisc-backend\b")


@pytest.mark.parametrize("name", ROTATABLE)
def test_rotate_one_says_to_restart_the_engine_after_ledger_pool(scratch, name):  # noqa: F811
    run_secrets(scratch)
    r = _run(scratch, "--rotate-one", name)
    assert r.returncode == 0, r.stderr[-2000:]
    printed = r.stdout + r.stderr
    assert _RESTART_ENGINE.search(printed), "the output does not say to restart aisc-backend after ledger-pool"
    assert printed.find("ledger-pool must exit 0") < _RESTART_ENGINE.search(printed).start(), \
        "the engine's restart must come after ledger-pool's exit 0"


def test_the_guide_restarts_the_engine_after_a_rotation():
    flat = " ".join((ROOT / "docs/guide.md").read_text().split())
    i = flat.find("--rotate-one")
    near = flat[i: i + 1200]
    assert _RESTART_ENGINE.search(near), "the guide's rotation procedure does not restart aisc-backend"
