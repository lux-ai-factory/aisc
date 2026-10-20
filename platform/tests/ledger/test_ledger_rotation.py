"""Rotating immudb's passwords.

`scripts/secrets.sh --rotate-one NAME` writes a new IMMUDB_ADMIN_PASSWORD, LEDGER_IMMUDB_PASSWORD or
ENGINE_IMMUDB_PASSWORD; a restart then finishes the rotation: immudb applies the superuser's at start
(IMMUDB_FORCE_ADMIN_PASSWORD), and ledger-pool's `top-up`, as the superuser, gives aisc_ledger and
aisc_engine the new values, only when the configured one does not log in (a change cuts the user's open
sessions), and the platform's store, whose logins failed meanwhile, works on its next call.

Every test here starts its own throwaway immudb (immudb_box), because it changes users' passwords or
recreates immudb; the platform database is the throwaway one of scripts/test-platform.sh.

    LEDGER_TESTS_REQUIRED=1 scripts/test-platform.sh tests/ledger/test_ledger_rotation.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid

import pytest

from tests.ledger.conftest import MADE, need, needs_db
from tests.ledger.immudb_box import (ImmudbBox, docker_available, logs_in, password, permissions, sql_grants)
from tests.ledger.test_engine_account import clerk_connect, clerk_rows, clerk_write

pytestmark = needs_db


@pytest.fixture
def box():
    need(docker_available(), "docker is not available for a throwaway immudb")
    b = ImmudbBox()
    yield b
    b.close()


class Gen:
    """One generation of the three immudb passwords."""

    def __init__(self, admin: str):
        self.admin, self.ledger, self.engine = admin, password(), password()

    def all(self):
        return (self.admin, self.ledger, self.engine)


def top_up(dsn: str, url: str, gen: Gen, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.endswith("IMMUDB_PASSWORD")}
    env.update({"PLATFORM_DATABASE_URL": dsn, "LEDGER_IMMUDB_URL": url, "IMMUDB_ADMIN_PASSWORD": gen.admin,
                "LEDGER_IMMUDB_PASSWORD": gen.ledger, "ENGINE_IMMUDB_PASSWORD": gen.engine})
    return subprocess.run([sys.executable, "-m", "platform_service.ledger.pool", "top-up", *args, "0"], env=env,
                          capture_output=True, text=True, timeout=180)


def no_secret(out: str, *gens: Gen) -> None:
    """No output holds any of the passwords, of any generation."""
    for g in gens:
        for i, secret in enumerate(g.all()):
            assert secret not in out, f"output holds password #{i} of a generation"


def store(url: str, pw: str):
    from platform_service.ledger.state import MemoryStateStore
    from platform_service.ledger.store import ImmudbLedger

    s = ImmudbLedger(url, user="aisc_ledger", password=pw, state_store=MemoryStateStore())
    MADE["servers"].add(s.server_id)
    return s


def ledger_session(url: str, pw: str, db: str):
    from immudb import ImmudbClient

    c = ImmudbClient(url)
    c.login("aisc_ledger", pw, database=db.encode())
    return c


def make_ledger_user(box, pw: str) -> str:
    """aisc_ledger with `pw`, the platform's log and one pool database, as the operator's script makes them."""
    from platform_service.ledger import pool
    from platform_service.ledger.naming import PLATFORM_DB, pool_name

    db = pool_name()
    pool.create_databases(box.url, admin_password=box.admin_password, names=[db, PLATFORM_DB],
                          grantee="aisc_ledger", grantee_password=pw)
    return db


def pool_db(box, ledger_pw: str) -> str:
    """One more ledger database for aisc_ledger (which top-up made), as the operator's script makes it."""
    from platform_service.ledger import pool
    from platform_service.ledger.naming import pool_name

    db = pool_name()
    pool.create_databases(box.url, admin_password=box.admin_password, names=[db], grantee="aisc_ledger",
                          grantee_password=ledger_pw)
    return db


def test_a_working_password_is_left_alone_and_its_sessions_live(box, monkeypatch, capsys):
    from immudb import ImmudbClient

    from platform_service.ledger import pool

    pw = password()
    db = make_ledger_user(box, pw)
    session = ledger_session(box.url, pw, db)
    session.set(b"before", b"1")
    calls = []
    real = ImmudbClient.changePassword
    monkeypatch.setattr(ImmudbClient, "changePassword", lambda self, *a, **k: calls.append(1) or real(self, *a, **k))
    assert pool.ensure_password(box.url, admin_password=box.admin_password, user="aisc_ledger", password=pw) is False
    assert calls == [], "changePassword was called for a password that works (it cuts open sessions)"
    session.set(b"after", b"1")                                 # the open session is still valid
    out = capsys.readouterr()
    assert pw not in out.out + out.err and box.admin_password not in out.out + out.err


def test_another_password_is_changed_and_nothing_else(box, capsys):
    from platform_service.ledger import pool

    from platform_service.ledger.naming import PLATFORM_DB

    old, new = password(), password()
    db = make_ledger_user(box, old)
    before = permissions(box.admin(), "aisc_ledger")
    assert pool.ensure_password(box.url, admin_password=box.admin_password, user="aisc_ledger", password=new) is True
    assert logs_in(box.url, "aisc_ledger", new, database=PLATFORM_DB)
    assert logs_in(box.url, "aisc_ledger", new, database=db)
    assert not logs_in(box.url, "aisc_ledger", old, database=PLATFORM_DB)
    assert permissions(box.admin(), "aisc_ledger") == before
    out = capsys.readouterr()
    for secret in (old, new, box.admin_password):
        assert secret not in out.out + out.err


def test_the_engine_accounts_rights_survive_a_password_change(box):
    from platform_service.ledger import engine_account, pool

    old, new = password(), password()
    engine_account.ensure_engine_account(box.url, admin_password=box.admin_password, password=old)
    before = (permissions(box.admin(), "aisc_engine"), sql_grants(box.admin(), "aisc_engine"))
    assert pool.ensure_password(box.url, admin_password=box.admin_password, user="aisc_engine", password=new) is True
    assert logs_in(box.url, "aisc_engine", new) and not logs_in(box.url, "aisc_engine", old)
    assert (permissions(box.admin(), "aisc_engine"), sql_grants(box.admin(), "aisc_engine")) == before
    clerk_write(clerk_connect(box.url, new))


def test_a_missing_user_is_not_made(box):
    from platform_service.ledger import pool

    assert pool.ensure_password(box.url, admin_password=box.admin_password, user="aisc_ledger",
                                password=password()) is False
    assert permissions(box.admin(), "aisc_ledger") is None


def test_an_engine_account_with_another_password_gets_the_new_one(box, capsys):
    from platform_service.ledger import engine_account

    old, new = password(), password()
    engine_account.ensure_engine_account(box.url, admin_password=box.admin_password, password=old)
    c = clerk_connect(box.url, old)
    clerk_write(c, "under the old password")
    assert engine_account.ensure_engine_account(box.url, admin_password=box.admin_password, password=new) is True
    assert logs_in(box.url, "aisc_engine", new) and not logs_in(box.url, "aisc_engine", old)
    assert permissions(box.admin(), "aisc_engine") == {"defaultdb": 1, "auditdb": 2}
    assert sql_grants(box.admin(), "aisc_engine") == {"SELECT", "CREATE", "INSERT"}
    assert {r[4] for r in clerk_rows(clerk_connect(box.url, new))} == {"under the old password"}
    out = capsys.readouterr()
    for secret in (old, new, box.admin_password):
        assert secret not in out.out + out.err


def test_top_up_brings_both_users_to_the_new_passwords_once(box, platform_dsn):
    from platform_service.ledger.naming import PLATFORM_DB

    first, second = Gen(box.admin_password), Gen(box.admin_password)
    r = top_up(platform_dsn, box.url, first)
    assert r.returncode == 0, r.stderr[-2000:]
    r = top_up(platform_dsn, box.url, second)
    out = r.stdout + r.stderr
    no_secret(out, first, second)
    assert r.returncode == 0, out[-2000:]
    assert "ledger user aisc_ledger: password changed" in r.stdout, r.stdout
    assert "engine account aisc_engine on auditdb: password changed" in r.stdout, r.stdout
    assert logs_in(box.url, "aisc_ledger", second.ledger, database=PLATFORM_DB)
    assert not logs_in(box.url, "aisc_ledger", first.ledger, database=PLATFORM_DB)
    assert logs_in(box.url, "aisc_engine", second.engine) and not logs_in(box.url, "aisc_engine", first.engine)
    store(box.url, second.ledger)                                  # the pool is usable with the new one

    session = ledger_session(box.url, second.ledger, PLATFORM_DB)  # the running platform, between two starts
    engine = clerk_connect(box.url, second.engine)                 # the running engine
    again = top_up(platform_dsn, box.url, second)
    assert again.returncode == 0, again.stderr[-2000:]
    no_secret(again.stdout + again.stderr, first, second)
    assert "ledger user aisc_ledger: password unchanged" in again.stdout, again.stdout
    assert "engine account aisc_engine on auditdb: unchanged" in again.stdout, again.stdout
    session.databaseListV2()                                       # its session was not cut
    clerk_write(engine, "still connected")


def test_the_whole_rotation_on_one_immudb_volume(box, platform_dsn):
    from platform_service.ledger.naming import PLATFORM_DB

    old = Gen(box.admin_password)
    r = top_up(platform_dsn, box.url, old)
    assert r.returncode == 0, r.stderr[-2000:]
    clerk_write(clerk_connect(box.url, old.engine), "before the rotation")
    db = pool_db(box, old.ledger)
    ledger = store(box.url, old.ledger)
    assert ledger.append(db, {"event_id": str(uuid.uuid4()), "action": "risk.rated"}) >= 1

    new = Gen(password())
    box.recreate(new.admin)                                        # compose recreating immudb on its volume
    r = top_up(platform_dsn, box.url, new, "--wait", "30")
    out = r.stdout + r.stderr
    no_secret(out, old, new)
    assert r.returncode == 0, out[-2000:]

    assert logs_in(box.url, "immudb", new.admin) and not logs_in(box.url, "immudb", old.admin)
    assert logs_in(box.url, "aisc_ledger", new.ledger, database=PLATFORM_DB)
    assert not logs_in(box.url, "aisc_ledger", old.ledger, database=PLATFORM_DB)
    assert logs_in(box.url, "aisc_engine", new.engine) and not logs_in(box.url, "aisc_engine", old.engine)
    assert sql_grants(box.admin(), "aisc_engine") == {"SELECT", "CREATE", "INSERT"}
    c = clerk_connect(box.url, new.engine)
    clerk_write(c, "after the rotation")
    assert {r[4] for r in clerk_rows(c)} == {"before the rotation", "after the rotation"}
    entries = store(box.url, new.ledger).scan(db, after_seq=0, limit=100)
    assert len(entries) >= 1


def test_the_platform_store_recovers_without_a_restart(box, platform_dsn):
    from platform_service.ledger.store import LedgerCredentials

    old = Gen(box.admin_password)
    r = top_up(platform_dsn, box.url, old)
    assert r.returncode == 0, r.stderr[-2000:]
    db = pool_db(box, old.ledger)
    new = Gen(box.admin_password)
    platform = store(box.url, new.ledger)                          # the platform, recreated before ledger-pool ran
    with pytest.raises(LedgerCredentials):
        platform.append(db, {"event_id": str(uuid.uuid4()), "action": "risk.rated"})
    r = top_up(platform_dsn, box.url, new)
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    assert platform.append(db, {"event_id": str(uuid.uuid4()), "action": "risk.rated"}) >= 1


# A grant, even one the user already has, ends its open sessions.


def test_a_second_create_databases_keeps_the_users_sessions(box, monkeypatch):
    from immudb import ImmudbClient

    from platform_service.ledger import pool
    from platform_service.ledger.naming import PLATFORM_DB, pool_name

    pw = password()
    db = make_ledger_user(box, pw)
    session = ledger_session(box.url, pw, db)
    session.set(b"before", b"1")
    calls = []
    real = ImmudbClient.changePermission
    monkeypatch.setattr(ImmudbClient, "changePermission", lambda self, *a, **k: calls.append(a) or real(self, *a, **k))
    pool.create_databases(box.url, admin_password=box.admin_password, names=[db, PLATFORM_DB],
                          grantee="aisc_ledger", grantee_password=pw)
    assert calls == [], f"a re-run granted {len(calls)} times (each grant ends the user's sessions)"
    session.set(b"after", b"1")                                 # still logged in
    new = pool_name()
    pool.create_databases(box.url, admin_password=box.admin_password, names=[new], grantee="aisc_ledger",
                          grantee_password=pw)
    assert len(calls) == 1 and permissions(box.admin(), "aisc_ledger")[new] == 2   # a new database: granted
