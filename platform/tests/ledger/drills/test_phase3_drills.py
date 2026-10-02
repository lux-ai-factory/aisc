"""Phase 3 drills (03-coding-plan.md), on a real immudb with the state in Postgres, opt-in:
LEDGER_DRILLS=1 (and LEDGER_DRILL_OUTAGE_SECONDS for the outage, 600 by default).

- the relay killed (SIGKILL) in the middle of a batch, several times;
- immudb stopped for a long stretch while people keep working;
- two relays (two platform workers) on one project at once.
After each: every event exactly once, the seqs contiguous, the index equal to the log, nothing rejected."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from tests.conftest import DSN
from tests.ledger.conftest import IMMUDB_URL, LEDGER_KEYS, LEDGER_USER_PASSWORD, MEMBER, OWNER, entries, log_of, relay_all
from tests.ledger.test_ledger_outbox import emit

pytestmark = pytest.mark.skipif(os.environ.get("LEDGER_DRILLS") != "1", reason="drills are opt-in: LEDGER_DRILLS=1")
PLATFORM = Path(__file__).resolve().parents[3]
CONTAINER = os.environ.get("LEDGER_ENV_TAG", "") + "-immudb"


@pytest.fixture
def busy_project(immudb_ledger, make_project, witnessed, mode):
    mode("record")
    p = make_project(OWNER, editors=(MEMBER,))

    def work(n):
        ids = []
        for i in range(n):
            rid = witnessed(MEMBER, "POST", "control_objectives", f"/control-objectives/p/{p['pid']}/api/projects/a1/ratings")
            ids.append(emit(p["pid"], "control_objectives_rw", {
                "event_id": str(uuid.uuid4()), "request_id": rid, "action": "risk.rated",
                "item_type": "risk", "item_id": f"r{uuid.uuid4().hex[:8]}"}))
        return ids
    return p, work


def _env():
    return {**os.environ, "PLATFORM_DATABASE_URL": DSN, "PLATFORM_LEDGER_KEYS": LEDGER_KEYS,
            "LEDGER_IMMUDB_URL": IMMUDB_URL, "LEDGER_IMMUDB_PASSWORD": LEDGER_USER_PASSWORD,
            "LEDGER_IMMUDB_PUBLIC_KEY": os.environ.get("LEDGER_TEST_IMMUDB_PUBLIC_KEY", "")}


def _relay_process(pid, loops=1):
    code = ("import sys\nfrom platform_service.ledger import relay\n"
            f"for _ in range({loops}):\n    relay.relay_once(sys.argv[1])\n")
    return subprocess.Popen([sys.executable, "-c", code, pid], cwd=PLATFORM, env=_env(),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def _check(store, pid, emitted, requests):
    import psycopg

    log = log_of(pid)
    all_entries = entries(store, log)
    assert [e.seq for e in all_entries] == list(range(1, len(all_entries) + 1)), "seqs not contiguous"
    ids = [e.event_id for e in all_entries]
    assert len(ids) == len(set(ids)), "an event twice"
    rated = {e.event_id for e in all_entries if e.action == "risk.rated"}
    assert rated == set(emitted), f"{len(set(emitted) - rated)} events missing"
    assert [e for e in all_entries if e.action == "ledger.rejected"] == []
    assert len([e for e in all_entries if e.action == "request.witnessed"]) >= requests
    with psycopg.connect(DSN) as conn:
        indexed = conn.execute("SELECT count(*) FROM ledger.event_index WHERE log = %s", (log,)).fetchone()[0]
    assert indexed == len(all_entries), "index and log disagree"
    return len(all_entries)


def test_drill_the_relay_killed_mid_batch(immudb_ledger, busy_project):
    p, work = busy_project
    emitted = work(40)
    kills = 0
    for delay in (0.4, 0.8, 1.2):
        proc = _relay_process(p["pid"])
        time.sleep(delay)
        if proc.poll() is None:
            proc.send_signal(signal.SIGKILL)
            kills += 1
        proc.wait()
    relay_all(p["pid"])
    n = _check(immudb_ledger, p["pid"], emitted, 40)
    print(f"\nDRILL kill: {kills} kills, {n} entries, contiguous, each once")
    assert kills >= 1, "the relay finished before any kill: raise the batch size"


def test_drill_two_relays_at_once(immudb_ledger, busy_project):
    p, work = busy_project
    emitted = work(10)
    procs = [_relay_process(p["pid"], loops=6) for _ in range(2)]
    emitted += work(20)                                              # people keep working meanwhile
    outs = [proc.communicate(timeout=300)[0] for proc in procs]
    assert all(proc.returncode == 0 for proc in procs), outs
    relay_all(p["pid"])
    n = _check(immudb_ledger, p["pid"], emitted, 30)
    print(f"\nDRILL two relays: {n} entries, contiguous, each once")


def test_drill_immudb_down_for_a_long_stretch(immudb_ledger, busy_project):
    p, work = busy_project
    seconds = int(os.environ.get("LEDGER_DRILL_OUTAGE_SECONDS", "600"))
    emitted = work(5)
    relay_all(p["pid"])
    subprocess.run(["docker", "stop", CONTAINER], check=True, capture_output=True)
    try:
        started, pending = time.time(), []
        while time.time() - started < seconds:
            emitted += work(3)
            pending.append(relay_all(p["pid"]).pending)              # never raises, never blocks the work
            time.sleep(min(30, seconds / 10))
    finally:
        subprocess.run(["docker", "start", CONTAINER], check=True, capture_output=True)
    for _ in range(60):
        try:
            immudb_ledger.databases()
            break
        except Exception:
            time.sleep(1)
    relay_all(p["pid"])
    n = _check(immudb_ledger, p["pid"], emitted, len(emitted))
    print(f"\nDRILL outage {seconds}s: pending grew {pending[0]} -> {pending[-1]}, then {n} entries, each once")
    assert pending[-1] > pending[0]
