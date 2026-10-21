"""The engine's immudb login outlives a day. immudb 1.11.1 ends a login token after --token-expiry-time
minutes (1440 by default); the engine's audit clerk (aisc_backend/audit/clerk.py) logs in again when that
happens, and two settings keep it rare, read-only here (`docker compose config`): immudb's token lifetime,
and aisc-backend restarting with immudb, whose restart ends every token.

The name was proven on a throwaway immudb 1.11.1 (w8/FIX-root.md): with IMMUDB_TOKEN_EXPIRY_TIME=1 a
token is refused ("please login") 80 s after its login; with 525600 it still works then."""
import json

import compose_cfg


def _services(tmp_path):
    r = compose_cfg.run(tmp_path)
    assert r.returncode == 0, r.stderr[-1000:]
    return json.loads(r.stdout)["services"]


def test_immudb_keeps_a_login_token_for_a_year(tmp_path):
    env = _services(tmp_path)["immudb"]["environment"]
    assert env["IMMUDB_TOKEN_EXPIRY_TIME"] == "525600"           # minutes


def test_the_engine_restarts_with_immudb_and_still_waits_for_its_account(tmp_path):
    after = _services(tmp_path)["aisc-backend"]["depends_on"]
    assert after["immudb"]["restart"] is True
    assert after["immudb"]["condition"] == "service_healthy"
    assert after["ledger-pool"]["condition"] == "service_completed_successfully"
