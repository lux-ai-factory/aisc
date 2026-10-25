"""How many calls the protocol doors make to systems under test at once: at most PLATFORM_FACADE_THREADS
across the platform, and at most PLATFORM_FACADE_RUN_CAP per run (its pass, or a key issued without
one), so one run's dataset cannot take every thread from another run. A call over a cap waits;
nothing is refused for capacity. Runs on the throwaway; the systems are local stubs that sleep."""
from __future__ import annotations

import threading
import time

import pytest

from platform_service.routes import facade
from tests.conftest import needs_database
from tests.connection_support import CONNECTIONS_TOKEN, new_secret
from tests.test_connection_facades import _env, stub  # noqa: F401  (fixtures)


@pytest.fixture(autouse=True)
def _fresh_limiters(monkeypatch):
    monkeypatch.setattr(facade, "_FACADE_LIMITER", None, raising=False)
    monkeypatch.setattr(facade, "_RUN_LIMITERS", {})
    monkeypatch.delenv("PLATFORM_FACADE_THREADS", raising=False)
    monkeypatch.delenv("PLATFORM_FACADE_RUN_CAP", raising=False)


class Gauge:
    """Calls in flight at a stub, overall and per label (the question asked), and when each ended."""

    def __init__(self, seconds: float, answer=None):
        self.seconds, self.answer = seconds, answer or (lambda seen: {"answer": "late"})
        self.lock = threading.Lock()
        self.now, self.most = 0, 0
        self.per, self.most_per = {}, {}
        self.arrived, self.ended = [], []

    def __call__(self, seen):
        label = (seen.json or {}).get("question")
        with self.lock:
            self.now += 1
            self.most = max(self.most, self.now)
            self.per[label] = self.per.get(label, 0) + 1
            self.most_per[label] = max(self.most_per.get(label, 0), self.per[label])
            self.arrived.append(time.monotonic())
        time.sleep(self.seconds)
        with self.lock:
            self.now -= 1
            self.per[label] -= 1
            self.ended.append(time.monotonic())
        return 200, self.answer(seen)


def rest(client, admin, project, stub, name, path):  # noqa: F811
    body = {"label": name, "kind": "rest", "base_url": stub.base, "path": path,
            "body_template": {"question": "{{input}}"}, "response_path": "answer", "timeout_s": 10,
            "secret": new_secret()}
    r = client.put(f"/projects/{project['slug']}/connections/{name}", json=body, headers=admin)
    assert r.status_code == 200, r.text
    return name


def run_key(client, project, name):
    """A run: its own pass naming the connection, and a run key issued under it."""
    run_pass = client.post("/internal/run-passes", json={"refs": [f"connection:{project['pid']}/{name}"]},
                           headers={"X-AISC-Service-Token": CONNECTIONS_TOKEN}).json()["pass"]
    r = client.post(f"/internal/projects/{project['pid']}/connections/{name}/run-keys",
                    headers={"X-AISC-Run-Pass": run_pass})
    assert r.status_code == 201, r.text
    return r.json()["key"]


def token_key(client, project, name):
    r = client.post(f"/internal/projects/{project['pid']}/connections/{name}/run-keys",
                    headers={"X-AISC-Service-Token": CONNECTIONS_TOKEN})
    assert r.status_code == 201, r.text
    return r.json()["key"]


def asking(shared, project, name, key, answers, input="q"):
    url = f"/internal/facade/{project['pid']}/{name}/aisc/ask"
    return threading.Thread(target=lambda: answers.append(
        shared.post(url, json={"input": input}, headers={"Authorization": f"Bearer {key}"})))


def run_all(threads):
    for t in threads:
        t.start()
    return threads


def join_all(threads, timeout=30):
    for t in threads:
        t.join(timeout)
    assert not any(t.is_alive() for t in threads), "a call never came back"


def test_the_settings_and_their_defaults(monkeypatch):
    assert facade.facade_threads() == 32 and facade.facade_run_cap() == 8
    for value, threads in (("5", 5), ("x", 32), ("0", 32)):
        monkeypatch.setenv("PLATFORM_FACADE_THREADS", value)
        assert facade.facade_threads() == threads, value
    monkeypatch.setenv("PLATFORM_FACADE_THREADS", "2")
    monkeypatch.setenv("PLATFORM_FACADE_RUN_CAP", "3")
    assert facade.facade_run_cap() == 2
    monkeypatch.delenv("PLATFORM_FACADE_THREADS")
    monkeypatch.setenv("PLATFORM_FACADE_RUN_CAP", "-1")
    assert facade.facade_run_cap() == 8


@needs_database
def test_one_run_holds_at_most_its_cap(client, admin, project, stub, monkeypatch):  # noqa: F811
    monkeypatch.setenv("PLATFORM_FACADE_THREADS", "4")
    monkeypatch.setenv("PLATFORM_FACADE_RUN_CAP", "2")
    gauge = Gauge(1.0)
    stub.route("POST", "/slow", gauge)
    name = rest(client, admin, project, stub, "slow", "/slow")
    key = run_key(client, project, name)
    answers = []
    with client as shared:
        join_all(run_all([asking(shared, project, name, key, answers) for _ in range(4)]))
    assert gauge.most <= 2, f"{gauge.most} calls of one run reached the system at once, over its cap of 2"
    assert len(answers) == 4 and all(a.status_code == 200 for a in answers), [a.text for a in answers]


@needs_database
def test_another_run_is_served_while_one_run_is_at_its_cap(client, admin, project, stub, monkeypatch):  # noqa: F811
    monkeypatch.setenv("PLATFORM_FACADE_THREADS", "3")
    monkeypatch.setenv("PLATFORM_FACADE_RUN_CAP", "2")
    stub.route("POST", "/slow", Gauge(1.5))
    stub.route("POST", "/fast", (200, {"answer": "now"}))
    slow = rest(client, admin, project, stub, "slow", "/slow")
    fast = rest(client, admin, project, stub, "fast", "/fast")
    key_a, key_b = run_key(client, project, slow), run_key(client, project, fast)
    answers_a, answers_b = [], []
    with client as shared:
        calls = run_all([asking(shared, project, slow, key_a, answers_a) for _ in range(4)])
        time.sleep(0.3)
        started = time.monotonic()
        b = asking(shared, project, fast, key_b, answers_b)
        b.start()
        b.join(10)
        waited = time.monotonic() - started
        join_all(calls)
    assert answers_b and answers_b[0].status_code == 200, answers_b and answers_b[0].text
    assert waited < 0.5, f"run B waited {waited:.2f}s behind run A"
    assert all(a.status_code == 200 for a in answers_a)


@needs_database
def test_sixteen_dataset_calls_and_a_slow_a2a_target_leave_the_witness_answering(client, admin, project, stub):  # noqa: F811
    dataset = Gauge(1.0)
    stub.route("POST", "/rows", dataset)
    agent_arrived = []

    def agent(seen):
        agent_arrived.append(time.monotonic())
        time.sleep(2.0)
        return 200, {"jsonrpc": "2.0", "id": seen.json["id"], "result": {
            "message": {"messageId": "m", "role": "ROLE_AGENT", "parts": [{"text": "pong"}]}}}

    stub.route("POST", "/rpc", agent)
    rows = rest(client, admin, project, stub, "rows", "/rows")
    r = client.put(f"/projects/{project['slug']}/connections/agent", headers=admin, json={
        "label": "An agent", "kind": "a2a", "base_url": stub.base, "path": "/rpc", "protocol_version": "1.0",
        "timeout_s": 10})
    assert r.status_code == 200, r.text
    key_a, key_b = run_key(client, project, rows), run_key(client, project, "agent")
    answers_a, answers_b = [], []
    send = {"jsonrpc": "2.0", "id": 1, "method": "SendMessage",
            "params": {"message": {"messageId": "m1", "role": "ROLE_USER", "parts": [{"text": "q"}]}}}
    with client as shared:
        calls = run_all([asking(shared, project, rows, key_a, answers_a) for _ in range(16)])
        time.sleep(0.2)
        b = threading.Thread(target=lambda: answers_b.append(shared.post(
            f"/internal/facade/{project['pid']}/agent/a2a", json=send, headers={"Authorization": f"Bearer {key_b}"})))
        b.start()
        time.sleep(0.3)
        started = time.monotonic()
        shared.get("/authz/witness")
        waited = time.monotonic() - started
        b.join(20)
        join_all(calls)
    assert waited < 0.5, f"/authz/witness waited {waited:.2f}s"
    assert dataset.most <= 8, f"{dataset.most} of run A's calls were in flight at once, over the run cap of 8"
    assert agent_arrived and agent_arrived[0] < max(dataset.ended), "run B waited for all of run A"
    assert len(answers_a) == 16 and all(a.status_code == 200 for a in answers_a), [a.text for a in answers_a]
    assert answers_b and answers_b[0].status_code == 200 and "result" in answers_b[0].json(), answers_b[0].text


@needs_database
def test_a_slot_is_freed_after_a_failure(client, admin, project, stub, monkeypatch):  # noqa: F811
    monkeypatch.setenv("PLATFORM_FACADE_RUN_CAP", "1")
    # a 500 is retried twice: three of them fail the first ask, the next answer serves the second
    stub.route("POST", "/flaky", (500, {"detail": "down"}), (500, {"detail": "down"}), (500, {"detail": "down"}),
               (200, {"answer": "up"}))
    name = rest(client, admin, project, stub, "flaky", "/flaky")
    key = run_key(client, project, name)
    url = f"/internal/facade/{project['pid']}/{name}/aisc/ask"
    headers = {"Authorization": f"Bearer {key}"}
    assert client.post(url, json={"input": "q"}, headers=headers).status_code == 502
    second = client.post(url, json={"input": "q"}, headers=headers)
    assert second.status_code == 200, second.text
    assert facade._RUN_LIMITERS == {}


@needs_database
def test_keys_without_a_pass_are_capped_per_key(client, admin, project, stub, monkeypatch):  # noqa: F811
    monkeypatch.setenv("PLATFORM_FACADE_THREADS", "4")
    monkeypatch.setenv("PLATFORM_FACADE_RUN_CAP", "1")
    gauge = Gauge(1.0)
    stub.route("POST", "/slow", gauge)
    name = rest(client, admin, project, stub, "slow", "/slow")
    k1, k2 = token_key(client, project, name), token_key(client, project, name)
    answers = []
    with client as shared:
        join_all(run_all([asking(shared, project, name, k, answers, input=label)
                          for k, label in ((k1, "k1"), (k1, "k1"), (k2, "k2"), (k2, "k2"))]))
    assert gauge.most <= 2, gauge.most
    assert gauge.most_per.get("k1", 0) <= 1 and gauge.most_per.get("k2", 0) <= 1, gauge.most_per
    assert len(answers) == 4 and all(a.status_code == 200 for a in answers), [a.text for a in answers]
