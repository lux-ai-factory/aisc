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
