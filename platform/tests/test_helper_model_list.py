"""The models a test tool can run, listed live with the tool's own connection, for the run form: chat models
first. The engine asks for them on an internal route with its token; the answer never carries the key. The
provider is a local fake, so no test reaches a real provider or uses a real key."""
from __future__ import annotations

import pytest

from tests.conftest import needs_database
from tests.http_stub import FakeServer
from tests.llm_support import SECRETS_KEY, new_key

pytestmark = needs_database

ENGINE_TOKEN = "engine-model-list-token-for-tests"
HEADER = "X-AISC-Service-Token"
LISTED = {"data": [{"id": "whisper-1"}, {"id": "gpt-4o-mini"}, {"id": "text-embedding-3-small"},
                   {"id": "gpt-4o"}, {"id": "dall-e-3"}, {"id": "omni-moderation-latest"}]}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_SECRETS_KEY", SECRETS_KEY)
    monkeypatch.setenv("PLATFORM_ENGINE_TOKEN", ENGINE_TOKEN)


@pytest.fixture
def fake():
    server = FakeServer()
    yield server
    server.close()


@pytest.fixture
def judge(project, fake):
    from platform_service import helper_store, llm_store

    key = new_key()
    helper_store.save(project["pid"], "judge", label="Judge", endpoint_url=fake.url + "/v1", roles=["judge"],
                      ciphertext=llm_store.encrypt(key), subject="t")
    return key


def models(client, project, name="judge", token=ENGINE_TOKEN, **headers):
    sent = {HEADER: token, **headers} if token else headers
    return client.get(f"/internal/projects/{project['pid']}/helpers/{name}/models", headers=sent)


def test_a_tools_models_are_listed_chat_models_first(client, project, fake, judge):
    fake.reply("/v1/models", LISTED)

    r = models(client, project)

    assert r.status_code == 200, r.text
    assert r.json() == {"models": ["gpt-4o", "gpt-4o-mini", "dall-e-3", "omni-moderation-latest",
                                   "text-embedding-3-small", "whisper-1"], "error": None}


def test_the_tools_key_goes_to_its_provider_and_never_into_the_answer(client, project, fake, judge):
    fake.reply("/v1/models", LISTED)

    r = models(client, project)

    [asked] = fake.seen("/v1/models")
    assert asked.header("Authorization") == f"Bearer {judge}"
    assert judge not in r.text


def test_a_provider_that_lists_nothing_gives_the_reason(client, project, fake, judge):
    fake.reply("/v1/models", {"detail": "no"}, status=401)

    r = models(client, project)

    assert r.status_code == 200
    assert r.json()["models"] == [] and r.json()["error"]


def test_no_such_tool_is_404(client, project, judge):
    assert models(client, project, name="nobody").status_code == 404


def test_only_the_engine_asks_and_only_inside_the_network(client, project, judge):
    assert models(client, project, token="wrong").status_code == 401
    assert models(client, project, **{"X-Forwarded-For": "1.2.3.4"}).status_code == 404
