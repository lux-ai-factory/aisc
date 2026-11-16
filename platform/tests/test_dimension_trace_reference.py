"""A measure that would hold a conversation keeps a reference to the recorded call instead (the engine
replaces the text with `trace:<evaluation plugin>#sha256=<digest>`). The platform turns such a reference
back into the calls of that test whose request or answer holds the text with that digest, so a person who
may read the trace can still find the conversation. Runs on the throwaway."""
from __future__ import annotations

import hashlib
import uuid

import pytest

from platform_service import run_trace
from tests.conftest import needs_database

pytestmark = needs_database


def _record(pid, run, plugin, monkeypatch, question, answer):
    monkeypatch.setattr(run_trace, "_evaluation_plugin", lambda _run: plugin)
    started = run_trace.now()
    run_trace.record(pid, run, "system-chat", "aisc", {"input": question}, "answered", {"output": answer}, None,
                     started, run_trace.now())


@pytest.fixture
def a_test_with_two_calls(project, monkeypatch):
    plugin = str(uuid.uuid4())
    run = "key:" + uuid.uuid4().hex + uuid.uuid4().hex
    _record(project["pid"], run, plugin, monkeypatch, "what is your name?", "I am a bot.")
    _record(project["pid"], run, plugin, monkeypatch, "where do you live?", "Nowhere.")
    return project["pid"], plugin


def test_a_dimension_reference_finds_its_calls(a_test_with_two_calls):
    pid, plugin = a_test_with_two_calls
    assert hasattr(run_trace, "seqs_with_text"), \
        "the trace cannot be searched by the digest a measure keeps: run_trace.seqs_with_text is missing"
    question = hashlib.sha256("what is your name?".encode()).hexdigest()
    answer = hashlib.sha256("Nowhere.".encode()).hexdigest()
    assert run_trace.seqs_with_text(pid, plugin, question) == [1]
    assert run_trace.seqs_with_text(pid, plugin, answer) == [2]
    assert run_trace.seqs_with_text(pid, plugin, "0" * 64) == []
    assert run_trace.seqs_with_text(pid, str(uuid.uuid4()), question) == []


def test_owners_and_editors_follow_a_reference_and_viewers_do_not(client, as_user, make_project, monkeypatch):
    from tests.conftest import ALICE

    made = make_project(editors=("ed",), viewers=("vic",))
    plugin = str(uuid.uuid4())
    run = "key:" + uuid.uuid4().hex + uuid.uuid4().hex
    _record(made["pid"], run, plugin, monkeypatch, "what is your name?", "I am a bot.")
    digest = hashlib.sha256("I am a bot.".encode()).hexdigest()
    path = f"/projects/{made['slug']}/runs/{plugin}/trace-ref/{digest}"
    for who in (ALICE, "ed"):
        answer = client.get(path, headers=as_user(who))
        assert answer.status_code == 200, answer.text
        assert answer.json() == {"seqs": [1]}
    assert client.get(path, headers=as_user("vic")).status_code == 403
