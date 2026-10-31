"""scripts/stackcheck, the Python harness the stack checks move to from their bash scripts.

Unit tests run in-process with a fake docker; the db-access group also runs against a throwaway Postgres with the
platform's roles and migrations (scripts/tests/isolation_bed.py), never the stack's. Passwords stay out of every
assertion message.
"""

from __future__ import annotations

import http.server
import json
import shutil
import subprocess
import sys
import threading
import urllib.parse

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
from stackcheck import db_access, harness  # noqa: E402
from stackcheck.__main__ import main  # noqa: E402
from stackcheck.stack import PASSWORD_OF, Stack  # noqa: E402


def answer(ok, text=""):
    return harness.Answer(ok, text)


# ------------------------------------------------------------------------------------------- the arguments

def test_an_unknown_group_is_refused(capsys):
    assert main(["no-such-group"]) == 2
    assert "db-access" in capsys.readouterr().err


def test_an_unknown_option_is_refused(capsys):
    assert main(["db-access", "--onyl", "x"]) == 2


def test_an_unknown_check_name_is_refused_with_the_names_it_has(capsys, monkeypatch):
    monkeypatch.setitem(harness.GROUPS, "db-access", lambda stack: [harness.Check("one", lambda: harness.PASS)])
    assert main(["db-access", "--only", "two"]) == 2
    assert "one" in capsys.readouterr().err


def test_only_runs_the_named_checks(capsys, monkeypatch):
    ran = []
    monkeypatch.setitem(harness.GROUPS, "db-access", lambda stack: [
        harness.Check(name, lambda name=name: ran.append(name) or harness.PASS) for name in ("a", "b", "c")])
    assert main(["db-access", "--only", "b", "--only", "c"]) == 0
    assert ran == ["b", "c"]


# ------------------------------------------------------------------------------------------- the reporter

def test_a_check_that_raises_fails_alone_with_its_error_and_the_rest_still_run(capsys):
    def boom():
        raise RuntimeError("no answer from the container")

    checks = [harness.Check("first", boom), harness.Check("second", lambda: harness.PASS)]
    passed, failed = harness.run_checks(checks)
    out = capsys.readouterr().out
    assert (passed, failed) == (1, 1)
    assert "FAIL first" in out and "RuntimeError: no answer from the container" in out and "PASS second" in out


def test_a_failure_shows_its_whole_detail(capsys):
    detail = "\n".join(f"line {i}" for i in range(40))
    harness.run_checks([harness.Check("long", lambda: harness.Result(False, detail))])
    out = capsys.readouterr().out
    assert "line 0" in out and "line 39" in out


# ------------------------------------------------------------------------------------- deny with a control

def test_a_denial_without_a_working_control_proves_nothing():
    result = harness.deny(lambda: answer(False, "permission denied"), control=lambda: answer(False, "no login"))
    assert not result.ok and "control" in result.detail and "no login" in result.detail


def test_an_allowed_probe_fails():
    result = harness.deny(lambda: answer(True), control=lambda: answer(True))
    assert not result.ok and "ALLOWED" in result.detail


def test_a_refusal_for_another_reason_fails_with_it():
    result = harness.deny(lambda: answer(False, 'ERROR:  relation "core.nope" does not exist'),
                          control=lambda: answer(True))
    assert not result.ok and "does not exist" in result.detail


def test_a_refusal_for_a_privilege_after_a_working_control_passes():
    result = harness.deny(lambda: answer(False, "ERROR:  permission denied for table project"),
                          control=lambda: answer(True))
    assert result.ok


def test_an_allowed_read_passes_and_a_refused_one_fails_with_why():
    assert harness.allow(lambda: answer(True)).ok
    refused = harness.allow(lambda: answer(False, "FATAL:  password authentication failed"))
    assert not refused.ok and "password authentication failed" in refused.detail


# ------------------------------------------------------------------------------- secrets stay off argv

class Recorder:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.calls = []
        self.result = (returncode, stdout, stderr)

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, *self.result)


def test_psql_passes_the_password_in_the_environment_and_the_sql_on_stdin(tmp_path, monkeypatch):
    monkeypatch.delenv("PLATFORM_RW_PASSWORD", raising=False)
    (tmp_path / "env.runtime").write_text("PLATFORM_RW_PASSWORD=pw-from-runtime-77\n")
    run = Recorder(stdout="1\n")
    stack = Stack(env_file=tmp_path / "env.runtime", container="pg", run=run)
    got = stack.psql("platform_rw", "platform", "select 1")
    assert got.ok and got.text == "1"
    argv, kw = run.calls[0]
    assert not any("pw-from-runtime-77" in word for word in argv), "the password is on the command line"
    assert argv[:4] == ["docker", "exec", "-i", "-e"] and "PGPASSWORD" in argv and "pg" in argv
    passed = kw["env"]["PGPASSWORD"] == "pw-from-runtime-77"
    assert passed, "PGPASSWORD does not reach docker's environment"
    assert "select 1" in kw["input"] and "select 1" not in " ".join(argv)
    assert kw["timeout"] > 0


def test_a_role_without_a_generated_password_uses_its_name(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHBOARD_RO_PASSWORD", raising=False)
    run = Recorder()
    Stack(env_file=tmp_path / "missing", container="pg", run=run).psql("dashboard_ro", "platform", "select 1")
    assert run.calls[0][1]["env"]["PGPASSWORD"] == "dashboard_ro"


def test_a_psql_that_does_not_answer_in_time_is_a_refusal_not_a_hang(tmp_path):
    def slow(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    got = Stack(env_file=tmp_path / "missing", container="pg", run=slow).psql("platform_rw", "platform", "select 1")
    assert not got.ok and "did not answer" in got.text


def test_the_container_is_this_installs_postgres(tmp_path, monkeypatch):
    monkeypatch.delenv("PGCONTAINER", raising=False)
    (tmp_path / "env.secrets").write_text("AISC_INSTALL=ab12cd\n")
    assert Stack(env_file=tmp_path / "env.runtime", secrets_file=tmp_path / "env.secrets").container == \
        "aisc-ab12cd-postgres"


def test_a_token_is_asked_for_with_the_password_in_the_body(tmp_path):
    seen = {}

    class Keycloak(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"])).decode()
            seen.update(path=self.path, form=urllib.parse.parse_qs(body))
            out = json.dumps({"access_token": "tok-123"}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *_):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Keycloak)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        token = Stack(env_file=tmp_path / "missing", keycloak_url=url).token("user", "pw-user-55")
    finally:
        server.shutdown()
    assert token == "tok-123"
    assert seen["path"] == "/realms/aisc/protocol/openid-connect/token"
    sent = seen["form"]["password"] == ["pw-user-55"] and seen["form"]["username"] == ["user"]
    assert sent, "the password did not reach the token endpoint in the request body"


# ------------------------------------------------------------------------------------------- db-access

#: the read-only checks of scripts/verify-db-access.sh this group carries (sections 2, 5's platform part, 6, and
#: 7 read from the catalogue): a port that drops one fails here
PORTED = {
    *(f"{role}: {what}" for role in ("qualification_rw", "control_objectives_rw", "controls_rw", "engine_rw",
                                     "report_composer_rw")
      for what in ("reads core.project", "reads core.project_member", "cannot write core.project",
                   "cannot remove members")),
    "dashboard_ro: cannot write core", "dashboard_ro: cannot create tables in platform",
    *(f"{role}: cannot create in public" for role in ("qualification_rw", "engine_rw", "dashboard_ro",
                                                      "platform_rw")),
    "platform_rw: can create a database", "controls_rw: a module cannot create a database",
    "engine_rw: nor can the engine",
}


def test_the_group_carries_every_read_only_check_of_the_bash_script(tmp_path):
    names = [c.name for c in db_access.checks(Stack(env_file=tmp_path / "missing", container="pg"))]
    assert len(names) == len(set(names))
    assert set(names) == PORTED
    bash = (ROOT / "scripts/verify-db-access.sh").read_text()
    for what in ("reads core.project_member", "cannot write core.project", "cannot remove members",
                 "cannot write core", "cannot create tables in platform", "cannot create in public",
                 "can create a database", "a module cannot create a database", "nor can the engine"):
        assert what in bash, what


def test_every_denial_rolls_back_whatever_it_was_let_do(tmp_path):
    """Read-only on a live stack: a probe that a broken grant lets through changes nothing."""
    run = Recorder(returncode=1, stderr="ERROR:  permission denied")
    stack = Stack(env_file=tmp_path / "missing", container="pg", run=run)
    for check in db_access.checks(stack):
        check.run()
    for argv, kw in run.calls:
        sql = kw["input"].strip().lower()
        assert sql.startswith("select") or (sql.startswith("begin;") and sql.endswith("rollback;")), sql


def test_verify_runs_the_group_with_the_stack_checks():
    assert 'bash -c "cd scripts && python3 -m stackcheck db-access"' in (ROOT / "scripts/verify.sh").read_text()


@pytest.mark.skipif(shutil.which("docker") is None, reason="needs docker for a throwaway Postgres")
def test_the_group_passes_on_a_bed_with_the_platforms_roles(tmp_path, monkeypatch, capsys):
    sys.path.insert(0, str(ROOT / "scripts/tests"))
    from isolation_bed import build

    for name in ("PGCONTAINER", "PGHOST", *PASSWORD_OF.values()):
        monkeypatch.delenv(name, raising=False)
    bed = build("stackcheck", projects=(), modules=False)
    try:
        assert not bed.problems, sorted(bed.problems)
        stack = Stack(env_file=tmp_path / "missing", container=bed.t.name, host="127.0.0.1")
        passed, failed = harness.run_checks(db_access.checks(stack))
        out = capsys.readouterr().out
        assert failed == 0, out
        assert passed == len(PORTED)
        # read-only: the probes left nothing behind
        assert bed.scalar("platform", "select count(*) from pg_tables where tablename like 'sneaky%'") == "0"
    finally:
        bed.stop()


def test_with_no_sign_in_address_no_token_is_asked_for_on_a_guessed_port(tmp_path, monkeypatch):
    """start may have moved the sign-in off its default port, so only this install's address is used."""
    monkeypatch.delenv("KEYCLOAK_URL", raising=False)
    monkeypatch.delenv("KEYCLOAK_URL_EXTERNAL", raising=False)

    def no_request(*_, **__):
        raise AssertionError("a token was asked for with no sign-in address")

    monkeypatch.setattr(urllib.request, "urlopen", no_request)
    stack = Stack(env_file=tmp_path / "missing", secrets_file=tmp_path / "missing")
    assert stack.keycloak_url == ""
    assert stack.token("user", "pw-user-55") == ""
