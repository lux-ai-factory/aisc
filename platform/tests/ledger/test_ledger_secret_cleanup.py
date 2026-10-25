"""Old plaintext plugin secrets leave the platform's copies (platform_service.ledger.secret_cleanup): the
`core.outbox` rows are masked, the frozen `ledger.content` is redacted, and each redaction is named by a
`ledger.content.redacted` entry in the project's own log, so an export still checks offline.

Set-up: a project; the engine's `engine.plugin.configured` events sent through the internal route, each citing
its own witnessed request; E1 holds the LangBiTe judge key (a shape the registry accepts, so it was frozen),
E2 the same configuration already masked; then the relay.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
import pytest

from tests.ledger.conftest import MEMBER, SUPERUSER_DSN, entries, log_of, need, needs_db, relay_all

pytestmark = needs_db
TOKEN = "engine-token-0123456789"
KEY = "lb-judge-0123456789abcdef"
PL = str(uuid.uuid4())
ROOT = Path(__file__).resolve().parents[3]
CHECKER = ROOT / "scripts" / "verify-ledger-export.py"
MIGRATION = ROOT / "platform" / "migrations" / "0014_ledger_content_redaction.sql"
PLATFORM = ROOT / "platform"


def cleanup():
    return importlib.import_module("platform_service.ledger.secret_cleanup")


def checker():
    spec = importlib.util.spec_from_file_location("verify_ledger_export", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _enforce(mode, monkeypatch):
    mode("enforce")
    monkeypatch.setenv("PLATFORM_LEDGER_ENGINE_TOKEN", TOKEN)


def content_of(config):
    return {"config_id": 1, "config": config, "settings": {}}


def post(client, pid, event):
    return client.post(f"/internal/projects/{pid}/ledger/events", json=event, headers={"X-AISC-Service-Token": TOKEN})


def configure(client, witnessed, pid, config, event_id=None) -> dict:
    """One engine.plugin.configured event as the engine sends it, citing its own witnessed request."""
    request_id = witnessed(MEMBER, "POST", "engine", f"/api/v1/plugins/{PL}/config", project_header=pid)
    event = {"event_id": event_id or str(uuid.uuid4()), "request_id": request_id, "action": "engine.plugin.configured",
             "item_type": "plugin", "item_id": PL, "details": {}, "content": content_of(config)}
    r = post(client, pid, event)
    assert r.status_code == 202, r.text
    return event


def query(sql, params=()):
    from platform_service import db

    with db.pool().connection() as conn:
        return conn.execute(sql, params).fetchall()


def frozen(log, event_id):
    rows = query("SELECT * FROM ledger.content WHERE log = %s AND event_id = %s", (log, event_id))
    return rows[0] if rows else None


def outbox_content(event_id):
    return query("SELECT content FROM core.outbox WHERE event_id = %s", (event_id,))[0]["content"]


def redactions(store, log):
    return [e for e in entries(store, log) if e.action == "ledger.content.redacted"]


@pytest.fixture
def leaked(project, client, witnessed, memory_ledger):
    """E1 (the judge key) and E2 (already masked), sent and relayed."""
    pid = project["pid"]
    e1 = configure(client, witnessed, pid, {"judge_api_key": KEY, "languages": ["en"]})
    e2 = configure(client, witnessed, pid, {"judge_api_key": "set", "languages": ["en"]})
    relay_all(pid)
    log = log_of(pid)
    assert frozen(log, e1["event_id"])["content"]["config"]["judge_api_key"] == KEY
    return {"pid": pid, "log": log, "e1": e1, "e2": e2, "store": memory_ledger}


# The schema


def test_the_content_table_carries_a_redaction_mark_that_must_be_consistent(platform_dsn):
    columns = {r["column_name"]: r["data_type"] for r in query(
        "SELECT column_name, data_type FROM information_schema.columns"
        " WHERE table_schema = 'ledger' AND table_name = 'content'")}
    assert columns.get("redacted_at") == "timestamp with time zone"
    assert columns.get("redaction") == "text"
    from platform_service import db

    log = "ledger" + uuid.uuid4().hex
    for values in (("{}", None, "a reason"),                 # a reason with no time
                   ('{"a": 1}', "now", "a reason")):          # a time, but the content is still there
        with db.pool().connection() as conn:
            with pytest.raises(psycopg.errors.CheckViolation):
                with conn.transaction():
                    conn.execute("INSERT INTO ledger.content (log, event_id, content, redacted_at, redaction)"
                                 " VALUES (%s, %s, %s::jsonb, %s::timestamptz, %s)",
                                 (log, str(uuid.uuid4()), values[0], values[1], values[2]))
    with psycopg.connect(platform_dsn, autocommit=False) as conn:
        conn.execute("SET search_path = core")
        conn.execute(MIGRATION.read_text())                  # a second time: no error
        conn.rollback()


# Count and apply


def test_count_finds_the_outbox_row_and_the_frozen_content_and_changes_nothing(leaked):
    module = cleanup()
    before = (outbox_content(leaked["e1"]["event_id"]), frozen(leaked["log"], leaked["e1"]["event_id"]),
              len(entries(leaked["store"], leaked["log"])))
    assert module.count([leaked["pid"]]) == [module.ProjectCounts(
        leaked["pid"], outbox_rows=1, contents=1, events=1, scan_rows=0, rotate=[(PL, "judge_api_key", 1)])]
    assert (outbox_content(leaked["e1"]["event_id"]), frozen(leaked["log"], leaked["e1"]["event_id"]),
            len(entries(leaked["store"], leaked["log"]))) == before


def test_apply_masks_redacts_and_logs_the_redaction(leaked):
    module = cleanup()
    pid, log, e1, e2 = leaked["pid"], leaked["log"], leaked["e1"]["event_id"], leaked["e2"]["event_id"]
    e2_before = frozen(log, e2)
    length = len(entries(leaked["store"], log))
    assert module.apply([pid]) == [module.ProjectCounts(
        pid, outbox_rows=1, contents=1, events=1, scan_rows=0, rotate=[(PL, "judge_api_key", 1)])]
    assert outbox_content(e1)["config"] == {"judge_api_key": "set", "languages": ["en"]}
    row = frozen(log, e1)
    assert row["content"] is None and row["redacted_at"] is not None and row["redaction"] == module.REASON
    assert frozen(log, e2) == e2_before
    after = entries(leaked["store"], log)
    assert len(after) == length + 1
    entry = after[-1].as_dict()
    assert (entry["action"], entry["actor_kind"], entry["source_app"], entry["program"], entry["item_type"],
            entry["item_id"], entry["project_pid"]) == (
        "ledger.content.redacted", "system", "platform", "secret-cleanup", "ledger", log, pid)
    assert entry["details"] == {"event_ids": [e1], "reason": module.REASON, "count": 1}
    [index] = query("SELECT reason FROM ledger.event_index WHERE log = %s AND event_id = %s", (log, entry["event_id"]))
    assert index["reason"] is None


def test_a_second_apply_does_nothing(leaked):
    module = cleanup()
    module.apply([leaked["pid"]])
    redacted_at = frozen(leaked["log"], leaked["e1"]["event_id"])["redacted_at"]
    length = len(entries(leaked["store"], leaked["log"]))
    assert module.apply([leaked["pid"]]) == [module.ProjectCounts(leaked["pid"])]
    assert len(entries(leaked["store"], leaked["log"])) == length
    assert frozen(leaked["log"], leaked["e1"]["event_id"])["redacted_at"] == redacted_at


# The export and its checker


def _exported(leaked):
    from platform_service.ledger import export

    cleanup().apply([leaked["pid"]])
    lines = export.lines(leaked["pid"])
    pem = leaked["store"].public_key_pem()
    return lines, pem.encode() if isinstance(pem, str) else pem


def _at(lines, event_id) -> int:
    """The index of the line of an event, which is the checker's line number minus one."""
    return next(i for i, line in enumerate(lines) if (line.get("entry") or {}).get("event_id") == event_id)


def _main(tmp_path, lines, pem, capsys):
    path, key = tmp_path / "e.jsonl", tmp_path / "k.pub"
    path.write_text("\n".join(json.dumps(line) for line in lines))
    key.write_bytes(pem)
    code = checker().main(["--public-key", str(key), str(path)])
    return code, capsys.readouterr().out


def test_a_redacted_content_is_marked_in_the_export_and_the_export_checks(leaked, tmp_path, capsys):
    module = cleanup()
    lines, pem = _exported(leaked)
    one, two = lines[_at(lines, leaked["e1"]["event_id"])], lines[_at(lines, leaked["e2"]["event_id"])]
    assert one.get("content_redacted") == module.REASON and "content" not in one
    assert two["content"] == content_of({"judge_api_key": "set", "languages": ["en"]})
    assert checker().check(lines, pem) == []
    code, out = _main(tmp_path, lines, pem, capsys)
    assert code == 0, out
    assert out.strip().splitlines()[-1].endswith(
        "; frozen contents checked; 1 frozen content redacted, each named by a ledger.content.redacted entry")


def _edit(leaked, how):
    module = cleanup()
    original = frozen(leaked["log"], leaked["e1"]["event_id"])["content"]
    lines, pem = _exported(leaked)
    one, two = _at(lines, leaked["e1"]["event_id"]), _at(lines, leaked["e2"]["event_id"])
    if how == "unnamed_mark":
        del lines[two]["content"]
        lines[two]["content_redacted"] = module.REASON
        return lines, pem, two, "marked redacted but no ledger.content.redacted entry names it"
    if how == "altered_content":
        lines[two]["content"] = content_of({"judge_api_key": "set", "languages": ["fr"]})
        return lines, pem, two, "the content isn't what was logged"
    if how == "content_and_mark":
        lines[one]["content"] = original
        return lines, pem, one, "both a content and a redaction mark"
    if how == "other_reason":
        lines[one]["content_redacted"] = "other"
        return lines, pem, one, "its redaction reason is not the one the log recorded"
    del lines[two]["content"]
    return lines, pem, two, "the entry has a content digest but the file has no content"


@pytest.mark.parametrize("how", ["unnamed_mark", "altered_content", "content_and_mark", "other_reason",
                                 "removed_content"])
def test_the_checker_refuses_a_mark_or_a_content_the_log_does_not_back(leaked, tmp_path, capsys, how):
    lines, pem, at, message = _edit(leaked, how)
    expected = f"line {at + 1}: {message}"
    assert expected in checker().check(lines, pem)
    code, out = _main(tmp_path, lines, pem, capsys)
    assert code == 1 and expected in out


# Crashes, chunks, undelivered rows, replays


def test_a_run_stopped_after_the_append_is_finished_by_the_next_run(leaked, monkeypatch):
    module = cleanup()
    calls = []

    def crash_once():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("stopped between the append and the update")

    monkeypatch.setattr(module, "_after_redaction_append", crash_once)
    with pytest.raises(RuntimeError):
        module.apply([leaked["pid"]])
    assert frozen(leaked["log"], leaked["e1"]["event_id"])["content"] is not None
    module.apply([leaked["pid"]])
    assert len(redactions(leaked["store"], leaked["log"])) == 1
    assert frozen(leaked["log"], leaked["e1"]["event_id"])["redacted_at"] is not None


def test_many_leaked_contents_are_redacted_in_chunks(project, client, witnessed, memory_ledger, monkeypatch):
    module = cleanup()
    monkeypatch.setattr(module, "CHUNK", 2)
    pid = project["pid"]
    ids = sorted(configure(client, witnessed, pid, {"judge_api_key": f"lb-judge-{i}-0123456789abcdef"})["event_id"]
                 for i in range(3))
    relay_all(pid)
    module.apply([pid])
    made = redactions(memory_ledger, log_of(pid))
    assert [e.details["count"] for e in made] == [2, 1]
    assert [i for e in made for i in e.details["event_ids"]] == ids


def test_an_undelivered_row_is_masked_before_it_is_frozen(project, client, witnessed, memory_ledger):
    from platform_service.ledger import secrets

    module = cleanup()
    pid = project["pid"]
    e3 = configure(client, witnessed, pid, {"judge_api_key": "lb-judge-other-0123456789"})
    [counts] = module.apply([pid])
    assert (counts.outbox_rows, counts.contents, counts.events) == (1, 0, 0)
    relay_all(pid)
    log = log_of(pid)
    content = frozen(log, e3["event_id"])["content"]
    assert content["config"] == {"judge_api_key": "set"}
    [entry] = [e for e in entries(memory_ledger, log) if e.event_id == e3["event_id"]]
    assert entry.content_sha256 == secrets.content_digest(pid, content)


def test_the_engines_masked_copy_of_an_event_is_a_replay(leaked, client):
    pid, e1 = leaked["pid"], leaked["e1"]
    stored = query("SELECT * FROM core.outbox WHERE event_id = %s", (e1["event_id"],))[0]
    masked = {**e1, "content": content_of({"judge_api_key": "set", "languages": ["en"]})}
    r = post(client, pid, masked)
    assert r.status_code == 202, r.text
    assert r.json() == {"queued": e1["event_id"], "replay": True}
    assert query("SELECT * FROM core.outbox WHERE event_id = %s", (e1["event_id"],))[0] == stored
    other = {**e1, "content": content_of({"judge_api_key": "set", "languages": ["de"]})}
    assert post(client, pid, other).status_code == 409


def test_a_project_outbox_row_with_a_secret_shape_is_counted_and_never_changed(leaked):
    need(SUPERUSER_DSN, "PLATFORM_TEST_SUPERUSER_URL is not set")
    from tests.ledger.test_ledger_outbox import as_superuser, emit, event

    module = cleanup()
    pid = leaked["pid"]
    event_id = emit(pid, "controls_rw", event(content={"note": "Bearer abc"}))
    before = as_superuser(pid, "SELECT * FROM ledger.outbox WHERE event_id = %s", (event_id,))
    [counts] = module.count([pid])
    assert counts.scan_rows == 1
    module.apply([pid])
    assert as_superuser(pid, "SELECT * FROM ledger.outbox WHERE event_id = %s", (event_id,)) == before


# The command line


def test_the_count_command_prints_counts_and_names_never_a_value(leaked):
    pid = leaked["pid"]
    r = subprocess.run([sys.executable, "-m", "platform_service.ledger.secret_cleanup", "count", "--project", pid],
                       cwd=PLATFORM, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        f"project {pid}: core.outbox rows_to_mask=1",
        f"project {pid}: ledger.content rows_to_redact=1 events_to_append=1",
        f"project {pid}: ledger.outbox rows_with_secret_shape=0 (scan only)",
        f"project {pid}: rotate item={PL} field=judge_api_key events=1",
        "total: rows_to_mask=1 rows_to_redact=1 events_to_append=1 rows_with_secret_shape=0",
    ]
    assert KEY not in r.stdout + r.stderr


def test_the_export_command_prints_the_export(leaked, capsys):
    from platform_service.ledger import export

    pid = leaked["pid"]
    assert cleanup().main(["export", pid]) == 0
    printed = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert printed == json.loads(json.dumps(export.lines(pid)))


def test_an_unknown_command_is_a_usage_error():
    r = subprocess.run([sys.executable, "-m", "platform_service.ledger.secret_cleanup", "nothing"],
                       cwd=PLATFORM, capture_output=True, text=True, timeout=120)
    assert r.returncode == 2


def test_with_the_ledger_down_the_outbox_is_masked_and_nothing_is_redacted(leaked, monkeypatch, capsys):
    from platform_service.ledger.store import LedgerUnavailable

    module = cleanup()
    pid = leaked["pid"]

    def down(*args, **kwargs):
        raise LedgerUnavailable("immudb did not answer")

    monkeypatch.setattr(leaked["store"], "append", down)
    [counts] = module.apply([pid])
    assert counts.error == "the ledger is unavailable; nothing redacted in this project"
    assert (counts.outbox_rows, counts.contents) == (1, 0)
    assert frozen(leaked["log"], leaked["e1"]["event_id"])["content"] is not None
    capsys.readouterr()
    assert module.main(["apply", "--project", pid]) == 5
    assert f"project {pid}: the ledger is unavailable; nothing redacted in this project" in capsys.readouterr().err


# The registry


def test_the_redaction_is_the_platforms_own_action():
    from platform_service.ledger.registry import REGISTRY, check

    action = REGISTRY["ledger.content.redacted"]
    assert (action.origin, tuple(action.emitters), tuple(action.actor_kinds)) == ("platform", (), ("system",))
    assert "emitter" in check({"event_id": str(uuid.uuid4()), "action": "ledger.content.redacted",
                               "item_type": "ledger", "item_id": "x"}, emitter="engine")
