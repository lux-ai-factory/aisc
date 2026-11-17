"""The backend, the worker and flower reach RabbitMQ with accounts of their own, none tagged administrator; the
administrator account is for operators only. A one-shot makes the accounts through the management API on every
start, with the passwords scripts/aisc.py keeps.

Read-only: the setup script is loaded with a fake sender (nothing is sent), compose resolved on copies.
"""

import importlib.util

import compose_cfg
from conftest import ROOT, aisc_py

SETUP = ROOT / "infra/rabbitmq/setup_users.py"
#: the declarations worker shares the run worker's environment, and so its broker account
SERVICE_USERS = {"aisc-backend": "aisc-engine", "aisc-eval-worker": "aisc-worker",
                 "aisc-eval-declarations-worker": "aisc-worker", "aisc-eval-flower": "aisc-flower"}


def _module():
    assert SETUP.is_file(), "no infra/rabbitmq/setup_users.py: every service uses the administrator account"
    spec = importlib.util.spec_from_file_location("setup_users", SETUP)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_every_service_user_is_made_without_the_administrator_tag(monkeypatch):
    m = _module()
    for name in ("RABBITMQ_ENGINE_PASSWORD", "RABBITMQ_WORKER_PASSWORD", "RABBITMQ_FLOWER_PASSWORD"):
        monkeypatch.setenv(name, "fake-" + name.lower())
    sent = []
    m.apply("http://rabbitmq:15672", ("admin", "fake"), m.wanted_users(), put=lambda path, body: sent.append((path, body)))
    users = {p.split("/")[-1]: b for p, b in sent if p.startswith("/api/users/")}
    assert set(users) == set(SERVICE_USERS.values())
    assert {b["tags"] for b in users.values()} == {""}
    assert all(p.startswith("/api/permissions/%2F/") for p, _ in sent if not p.startswith("/api/users/"))


def test_each_service_uses_its_own_broker_account(tmp_path):
    s = compose_cfg.config(tmp_path, "inspect")["services"]
    who = {n: s[n]["environment"]["CELERY_BROKER_URL"].split("//")[1].split(":")[0] for n in SERVICE_USERS}
    assert who == SERVICE_USERS


def test_the_accounts_are_made_by_a_one_shot_after_rabbitmq_is_healthy(tmp_path):
    s = compose_cfg.config(tmp_path)["services"]
    assert "rabbitmq-setup" in s, "no one-shot makes the service accounts"
    assert s["rabbitmq-setup"]["depends_on"]["rabbitmq"]["condition"] == "service_healthy"
    assert s["rabbitmq"].get("healthcheck"), "rabbitmq has no healthcheck to wait for"


def test_the_service_passwords_are_kept_and_renewed_on_rotate():
    m = aisc_py()
    wanted = {"RABBITMQ_ENGINE_PASSWORD", "RABBITMQ_WORKER_PASSWORD", "RABBITMQ_FLOWER_PASSWORD"}
    assert wanted - {n for n, _ in m.SECRETS} == set(), "scripts/aisc.py makes no RabbitMQ service passwords"
    assert wanted - set(m.FRESH_ON_ROTATE) == set()


def test_rabbitmq_is_healthy_only_once_its_api_and_broker_ports_listen(tmp_path):
    """`rabbitmq-diagnostics ping` answers as soon as the node boots, before the management API (15672) that the
    one-shot calls and the broker port (5672) the services use are open: a start on a slow machine ran the
    one-shot too early and it was refused."""
    test = compose_cfg.config(tmp_path)["services"]["rabbitmq"]["healthcheck"]["test"]
    command = " ".join(test)
    assert "check_port_listener 15672" in command
    assert "check_port_listener 5672" in command


class _Answer:
    status = 204

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_the_one_shot_waits_while_the_management_api_refuses_connections():
    import urllib.error
    m = _module()
    tries, waits = [], []

    def opener(request, timeout):
        tries.append(request.full_url)
        if len(tries) < 3:
            raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
        return _Answer()

    put = m.sender("http://rabbitmq:15672", ("admin", "fake"), opener=opener, sleep=waits.append, wait_s=60)
    put("/api/users/aisc-engine", {"password": "x", "tags": ""})
    assert len(tries) == 3
    assert waits and all(w > 0 for w in waits)


def test_the_one_shot_gives_up_with_its_reason_once_the_wait_is_over():
    import urllib.error
    import pytest
    m = _module()
    clock = [0.0]

    def opener(request, timeout):
        raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))

    def sleep(seconds):
        clock[0] += seconds

    put = m.sender("http://rabbitmq:15672", ("admin", "fake"), opener=opener, sleep=sleep, wait_s=10,
                   clock=lambda: clock[0])
    with pytest.raises(SystemExit, match="RabbitMQ's management API at http://rabbitmq:15672 did not answer"):
        put("/api/users/aisc-engine", {"password": "x", "tags": ""})
    assert clock[0] >= 10


def test_a_refusal_by_rabbitmq_itself_is_not_waited_out():
    """An HTTP error (a wrong administrator password, a bad body) is an answer: retrying would only hide it."""
    import io
    import urllib.error
    import pytest
    m = _module()
    tries = []

    def opener(request, timeout):
        tries.append(1)
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(b""))

    put = m.sender("http://rabbitmq:15672", ("admin", "wrong"), opener=opener, sleep=lambda s: None, wait_s=60)
    with pytest.raises(urllib.error.HTTPError):
        put("/api/users/aisc-engine", {"password": "x", "tags": ""})
    assert tries == [1]
