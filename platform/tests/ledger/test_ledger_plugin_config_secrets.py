"""Saving a plugin configuration keeps each key typed into its form as a project secret: the engine sends one
secret event per kept key, then the configuration, all citing the save's request. The relay accepts them against
the REAL registry, up to sixteen keys per save, and refuses a secret event that cites any other plugin request."""
from __future__ import annotations

import uuid

import pytest

from tests.ledger.conftest import MEMBER, entries, log_of, needs_db, relay_all
from tests.ledger.test_ledger_step4_engine import TOKEN, rejected, send  # noqa: F401  (TOKEN: the engine's)

pytestmark = needs_db
PL = str(uuid.uuid4())
SAVE = f"/api/v1/plugins/{PL}/config"


@pytest.fixture(autouse=True)
def _enforce(mode, monkeypatch):
    mode("enforce")
    monkeypatch.setenv("PLATFORM_LEDGER_ENGINE_TOKEN", TOKEN)


def _secret(client, project, request_id, action="engine.secret.created", **details):
    send(client, project, request_id, action, "secret", str(uuid.uuid4()), details=details)


def test_a_save_that_keeps_keys_as_secrets_is_accepted_whole(client, project, memory_ledger, witnessed):
    request_id = witnessed(MEMBER, "POST", "engine", SAVE, project_header=project["pid"])
    _secret(client, project, request_id, key="demoa_model_credential")
    _secret(client, project, request_id, key="demoa_judge_api_key")
    _secret(client, project, request_id, "engine.secret.updated", key="demoa_embeddings_api_key", changed=["value"])
    send(client, project, request_id, "engine.plugin.configured", "plugin", PL,
         content={"config_id": 7, "config": {"threshold": 0.5, "model_credential": "set"},
                  "settings": {"config.model_credential": str(uuid.uuid4())}})
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []
    assert [e.action for e in entries(memory_ledger, log_of(project["pid"]))
            if e.action.startswith("engine.")] == ["engine.secret.created", "engine.secret.created",
                                                    "engine.secret.updated", "engine.plugin.configured"]


def test_a_save_keeps_at_most_sixteen_keys(client, project, memory_ledger, witnessed):
    request_id = witnessed(MEMBER, "POST", "engine", SAVE, project_header=project["pid"])
    for n in range(17):
        _secret(client, project, request_id, key=f"demoa_k{n:02d}_api_key")
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == ["per_request"]
    assert len([e for e in entries(memory_ledger, log_of(project["pid"]))
                if e.action == "engine.secret.created"]) == 16


def test_a_save_never_deletes_a_secret_and_a_restore_makes_none(client, project, memory_ledger, witnessed):
    save = witnessed(MEMBER, "POST", "engine", SAVE, project_header=project["pid"])
    _secret(client, project, save, "engine.secret.deleted", key="demoa_model_credential")
    restore = witnessed(MEMBER, "POST", "engine", f"/api/v1/plugins/{PL}/configs/1/restore",
                        project_header=project["pid"])
    _secret(client, project, restore, key="demoa_model_credential")
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == ["cause", "cause"]
