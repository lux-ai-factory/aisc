"""The per-project LLM routes and the internal resolve route (01-specs.md section 2 and 5).

Proves S2.1, S2.2, S2.4 to S2.10, S2.11 (API side), S2.12, S2.14, S2.15, S2.20 to S2.26,
S5.1, S5.3 (API), S5.4, S5.5 (token, forwarded), S5.7. Runs against the throwaway
database (PLATFORM_TEST_DATABASE_URL) with the `client`/`as_user` fixtures; a platform
admin is `roles=("admin",)`. Provider listing calls go to a fake server: the hosted
URL constants in `llm_catalogue.MODELS_URL` are monkeypatched (S2.18).
"""
from __future__ import annotations

import importlib
import inspect
import json
import logging

import psycopg
import pytest
from cryptography.fernet import Fernet
from psycopg.conninfo import make_conninfo

from platform_service import projectdb
from tests.conftest import needs_database
from tests.llm_support import INTERNAL_TOKEN, SECRETS_KEY, FakeServer, new_key

pytestmark = needs_database

ALICE = "00000000-0000-0000-0000-00000000a11c"   # owns the project, not an admin
BOB = "00000000-0000-0000-0000-0000000000b0"     # a member (editor)
MALLORY = "00000000-0000-0000-0000-0000000000ee"  # a stranger
IDS = {"anthropic", "compatible", "deepseek", "google", "groq", "meta", "mistral",
       "ollama", "openai", "openrouter", "qwen", "together", "xai"}
NOT_VALID_KEY = "the key is not a valid API key string"


@pytest.fixture(autouse=True)
def _secrets(monkeypatch):
    monkeypatch.setenv("PLATFORM_SECRETS_KEY", SECRETS_KEY)
    monkeypatch.setenv("PLATFORM_INTERNAL_TOKEN", INTERNAL_TOKEN)
    monkeypatch.delenv("PLATFORM_OLLAMA_BASE_URL", raising=False)


@pytest.fixture
def admin(as_user):
    return as_user("root", roles=("admin",))


@pytest.fixture
def project(client, as_user, unique):
    made = client.post("/projects", json={"name": unique("llm")}, headers=as_user(ALICE))
    assert made.status_code == 201, made.text
    body = made.json()
    added = client.post(f"/projects/{body['slug']}/members", json={"subject": BOB, "role": "editor"},
                        headers=as_user(ALICE))
    assert added.status_code in (200, 201), added.text
    return body


@pytest.fixture
def fake():
    server = FakeServer()
    yield server
    server.close()


@pytest.fixture
def cat():
    return importlib.import_module("platform_service.llm_catalogue")


def base(project, key="slug"):
    return f"/projects/{project[key]}/llm"


def put_provider(client, project, provider, headers, **body):
    return client.put(f"{base(project)}/providers/{provider}", json=body, headers=headers)


def put_system(client, project, system, headers, provider, model):
    return client.put(f"{base(project)}/systems/{system}", json={"provider": provider, "model": model},
                      headers=headers)


def resolve(client, pid, system="card_agent", token=INTERNAL_TOKEN, headers=None):
    h = dict(headers or {})
    if token is not None:
        h["X-AISC-Service-Token"] = token
    return client.get(f"/internal/projects/{pid}/llm/{system}", headers=h)


def provider_entry(client, project, headers, provider):
    listed = client.get(base(project), headers=headers)
    assert listed.status_code == 200, listed.text
    return {p["id"]: p for p in listed.json()["providers"]}[provider]


def rows(dsn, project, sql="select * from llm.provider"):
    name = projectdb.database_name(project["pid"])
    with psycopg.connect(make_conninfo(dsn, dbname=name)) as conn:
        cur = conn.execute(sql)
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def run_sql(dsn, project, sql, params=()):
    name = projectdb.database_name(project["pid"])
    with psycopg.connect(make_conninfo(dsn, dbname=name)) as conn:
        conn.execute(sql, params)
        conn.commit()


def all_routes(project, key="slug"):
    b = f"/projects/{project[key]}/llm"
    return [
        ("GET", b, None),
        ("PUT", f"{b}/providers/openai", {"api_key": new_key()}),
        ("DELETE", f"{b}/providers/openai", None),
        ("GET", f"{b}/providers/openai/models", None),
        ("PUT", f"{b}/systems/card_agent", {"provider": "ollama", "model": "gemma3"}),
        ("DELETE", f"{b}/systems/card_agent", None),
    ]


def call(client, method, path, body, headers):
    if body is None:
        return client.request(method, path, headers=headers)
    return client.request(method, path, json=body, headers=headers)


# ── S2.1 admin only, S2.2 signed in ──────────────────────────────────────────


def test_s2_1_a_member_who_is_not_an_admin_gets_403_on_every_llm_route(client, as_user, project):
    for who in (ALICE, BOB):
        for method, path, body in all_routes(project):
            r = call(client, method, path, body, as_user(who))
            assert r.status_code == 403, (who, method, path, r.status_code, r.text)


def test_s2_1_a_stranger_gets_404_on_every_llm_route(client, as_user, admin, project):
    assert client.get(base(project), headers=admin).status_code == 200  # the routes exist
    for method, path, body in all_routes(project):
        r = call(client, method, path, body, as_user(MALLORY))
        assert r.status_code == 404, (method, path, r.status_code, r.text)


def test_s2_1_an_unknown_project_is_404_even_for_an_admin(client, admin):
    fake_project = {"slug": "pytest-no-such-project-llm"}
    for method, path, body in all_routes(fake_project):
        r = call(client, method, path, body, admin)
        assert r.status_code == 404, (method, path, r.status_code, r.text)
        assert r.json()["detail"] != "Not Found", "the route itself is missing"


def test_s2_1_the_project_may_be_named_by_slug_or_pid(client, admin, project):
    for key in ("slug", "pid"):
        r = client.get(base(project, key), headers=admin)
        assert r.status_code == 200, (key, r.text)


def test_s2_2_an_unauthenticated_call_is_401(client, project):
    for method, path, body in all_routes(project):
        r = call(client, method, path, body, {})
        assert r.status_code == 401, (method, path, r.status_code)


# ── S2.4 and S2.5 the catalogue as the page sees it ──────────────────────────


def test_s2_4_the_listing_has_every_provider_and_both_systems(client, admin, project):
    body = client.get(base(project), headers=admin).json()
    assert set(body) == {"providers", "systems"}
    assert {p["id"] for p in body["providers"]} == IDS
    for p in body["providers"]:
        assert set(p) == {"id", "label", "key_required", "has_key", "base_url", "base_url_editable",
                          "usable", "updated_at"}, p
        assert p["has_key"] is False and p["updated_at"] is None
    assert body["systems"] == [
        {"id": "card_agent", "label": "Card agent (Qualification)", "choice": None},
        {"id": "risk_mapper", "label": "Risk mapper (Control objectives)", "choice": None},
    ]


def test_s2_5_usable_follows_key_and_base_url(client, admin, project):
    listed = {p["id"]: p for p in client.get(base(project), headers=admin).json()["providers"]}
    for pid, p in listed.items():
        if pid == "ollama":
            assert p["usable"] is True and p["key_required"] is False
        elif pid == "compatible":
            assert p["usable"] is False and p["base_url"] is None
        else:
            assert p["usable"] is False and p["key_required"] is True and p["base_url"] is None
    assert put_provider(client, project, "openai", admin, api_key=new_key()).status_code == 200
    assert put_provider(client, project, "compatible", admin, base_url="http://127.0.0.1:9/v1").status_code == 200
    listed = {p["id"]: p for p in client.get(base(project), headers=admin).json()["providers"]}
    assert listed["openai"]["usable"] is True and listed["openai"]["has_key"] is True
    assert listed["compatible"]["usable"] is True
    assert listed["compatible"]["base_url"] == "http://127.0.0.1:9/v1"
    assert listed["compatible"]["has_key"] is False


def test_s2_5_ollama_defaults_to_host_docker_internal(client, admin, project):
    assert provider_entry(client, project, admin, "ollama")["base_url"] == "http://host.docker.internal:11434"


def test_s2_5_ollama_default_comes_from_platform_ollama_base_url(client, admin, project, monkeypatch):
    monkeypatch.setenv("PLATFORM_OLLAMA_BASE_URL", "http://10.1.2.3:11434")
    assert provider_entry(client, project, admin, "ollama")["base_url"] == "http://10.1.2.3:11434"


# ── S2.7 to S2.10 keys and endpoints ─────────────────────────────────────────


def test_s2_7_saving_a_key_answers_the_provider_entry(client, admin, project):
    r = put_provider(client, project, "openai", admin, api_key=new_key())
    assert r.status_code == 200, r.text
    entry = r.json()
    assert entry["id"] == "openai" and entry["has_key"] is True and entry["usable"] is True
    assert isinstance(entry["updated_at"], str)


def test_s2_7_an_absent_key_keeps_the_stored_one(client, admin, project, dsn):
    key = new_key()
    assert put_provider(client, project, "compatible", admin, api_key=key,
                        base_url="http://127.0.0.1:9/v1").status_code == 200
    before = rows(dsn, project)[0]["ciphertext"]
    r = put_provider(client, project, "compatible", admin, base_url="http://127.0.0.1:10/v1")
    assert r.status_code == 200, r.text
    assert r.json()["has_key"] is True
    assert rows(dsn, project)[0]["ciphertext"] == before


def test_s2_7_a_new_key_replaces_the_old_one(client, admin, project, dsn):
    put_provider(client, project, "openai", admin, api_key=new_key())
    second = new_key()
    assert put_provider(client, project, "openai", admin, api_key=second).status_code == 200
    token = rows(dsn, project)[0]["ciphertext"]
    assert Fernet(SECRETS_KEY.encode()).decrypt(token.encode()).decode() == second


def test_s2_7_an_empty_base_url_clears_it(client, admin, project):
    put_provider(client, project, "compatible", admin, base_url="http://127.0.0.1:9/v1")
    r = put_provider(client, project, "compatible", admin, base_url="")
    assert r.status_code == 200, r.text
    assert r.json()["base_url"] is None and r.json()["usable"] is False


def test_s2_7_a_base_url_for_a_hosted_provider_is_422(client, admin, project):
    r = put_provider(client, project, "openai", admin, api_key=new_key(), base_url="http://127.0.0.1:9/v1")
    assert r.status_code == 422
    assert provider_entry(client, project, admin, "openai")["has_key"] is False


def test_s2_7_an_empty_body_is_422(client, admin, project):
    assert put_provider(client, project, "openai", admin).status_code == 422


def test_s2_7_an_unknown_provider_is_404(client, admin, project):
    r = put_provider(client, project, "telepathy", admin, api_key=new_key())
    assert r.status_code == 404
    assert r.json()["detail"] != "Not Found", "the route itself is missing"


@pytest.mark.parametrize("bad", ["", "   ", "sk-a b", "sk-a\tb", "sk-a\nb", "sk-a\x00b", "sk-\x7f", "k" * 4097])
def test_s2_8_a_malformed_key_is_422_with_a_fixed_message(client, admin, project, bad):
    r = put_provider(client, project, "openai", admin, api_key=bad)
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == NOT_VALID_KEY
    if bad.strip():
        assert bad.strip() not in r.text


def test_s2_8_surrounding_whitespace_is_stripped_and_4096_characters_accepted(client, admin, project, dsn):
    key = "sk-" + "k" * 4093
    assert put_provider(client, project, "openai", admin, api_key=f"  {key}\n").status_code == 200
    token = rows(dsn, project)[0]["ciphertext"]
    assert Fernet(SECRETS_KEY.encode()).decrypt(token.encode()).decode() == key


@pytest.mark.parametrize("bad", [
    "ftp://127.0.0.1/v1", "127.0.0.1:11434", "http://", "http://user:pass@127.0.0.1/v1",
    "http://127.0.0.1/v1?x=1", "http://127.0.0.1/v1#f", "http://127.0.0.1/" + "v" * 500, "javascript:alert(1)",
])
def test_s2_9_a_bad_base_url_is_422(client, admin, project, bad):
    r = put_provider(client, project, "compatible", admin, base_url=bad)
    assert r.status_code == 422, (bad, r.text)
    assert provider_entry(client, project, admin, "compatible")["base_url"] is None


@pytest.mark.parametrize("good", ["http://127.0.0.1:8000/v1", "https://llm.example.org/v1", "http://ollama:11434"])
def test_s2_9_a_good_base_url_is_stored(client, admin, project, good):
    r = put_provider(client, project, "compatible", admin, base_url=good)
    assert r.status_code == 200, r.text
    assert r.json()["base_url"] == good


def test_s2_10_deleting_a_stored_key_is_204_and_removes_the_row(client, admin, project, dsn):
    put_provider(client, project, "openai", admin, api_key=new_key())
    r = client.delete(f"{base(project)}/providers/openai", headers=admin)
    assert r.status_code == 204, r.text
    assert rows(dsn, project) == []
    assert provider_entry(client, project, admin, "openai")["has_key"] is False


def test_s2_10_deleting_nothing_is_404(client, admin, project):
    r = client.delete(f"{base(project)}/providers/openai", headers=admin)
    assert r.status_code == 404
    assert r.json()["detail"] != "Not Found", "the route itself is missing"


def test_s2_10_deleting_a_key_a_system_uses_is_409_naming_it(client, admin, project, dsn):
    put_provider(client, project, "openai", admin, api_key=new_key())
    assert put_system(client, project, "risk_mapper", admin, "openai", "gpt-4o-mini").status_code == 200
    r = client.delete(f"{base(project)}/providers/openai", headers=admin)
    assert r.status_code == 409
    assert "risk_mapper" in r.text
    assert len(rows(dsn, project)) == 1


# ── S2.11 and S2.12 the Fernet key ───────────────────────────────────────────


def test_s2_11_without_platform_secrets_key_a_key_write_is_503(client, admin, project, monkeypatch, dsn):
    monkeypatch.delenv("PLATFORM_SECRETS_KEY")
    r = put_provider(client, project, "openai", admin, api_key=new_key())
    assert r.status_code == 503
    assert r.json()["detail"] == "PLATFORM_SECRETS_KEY is not set"
    assert rows(dsn, project) == []


@pytest.mark.parametrize("bad", ["not-a-fernet-key", SECRETS_KEY + ",garbage"])
def test_s2_11_a_malformed_platform_secrets_key_is_503(client, admin, project, monkeypatch, bad):
    monkeypatch.setenv("PLATFORM_SECRETS_KEY", bad)
    r = put_provider(client, project, "openai", admin, api_key=new_key())
    assert r.status_code == 503
    assert r.json()["detail"] == "PLATFORM_SECRETS_KEY is not a list of Fernet keys"


def test_s2_11_the_catalogue_still_answers_without_the_secrets_key(client, admin, project, monkeypatch):
    put_provider(client, project, "openai", admin, api_key=new_key())
    monkeypatch.delenv("PLATFORM_SECRETS_KEY")
    assert provider_entry(client, project, admin, "openai")["has_key"] is True


def test_s2_11_s2_25_a_resolve_that_needs_a_key_is_503_without_the_secrets_key(client, admin, project, monkeypatch):
    put_provider(client, project, "openai", admin, api_key=new_key())
    put_system(client, project, "card_agent", admin, "openai", "gpt-4o-mini")
    monkeypatch.delenv("PLATFORM_SECRETS_KEY")
    r = resolve(client, project["pid"])
    assert r.status_code == 503
    assert "PLATFORM_SECRETS_KEY" in r.json()["detail"]


def test_s2_12_an_unreadable_key_is_reported_by_models_and_resolve(client, admin, project, monkeypatch):
    put_provider(client, project, "openai", admin, api_key=new_key())
    put_system(client, project, "card_agent", admin, "openai", "gpt-4o-mini")
    monkeypatch.setenv("PLATFORM_SECRETS_KEY", Fernet.generate_key().decode())
    message = "the stored key for openai cannot be decrypted; enter it again"
    models = client.get(f"{base(project)}/providers/openai/models", headers=admin)
    assert models.status_code == 200
    assert models.json() == {"models": [], "error": message}
    r = resolve(client, project["pid"])
    assert r.status_code == 409
    assert r.json()["detail"] == message


# ── S2.14 and S5.7 request validation never echoes, writes are JSON only ─────


def _no_echo(response, value):
    assert value not in response.text
    body = response.json()
    detail = body.get("detail")
    items = detail if isinstance(detail, list) else []
    for item in items:
        assert "input" not in item and "ctx" not in item, item


def test_s2_14_a_key_sent_as_a_number_is_422_without_the_value(client, admin, project):
    r = client.put(f"{base(project)}/providers/openai", json={"api_key": 987654321987}, headers=admin)
    assert r.status_code == 422
    _no_echo(r, "987654321987")


def test_s2_14_a_non_json_body_is_422_without_the_value(client, admin, project):
    secret = new_key()
    r = client.put(f"{base(project)}/providers/openai", content=f'{{"api_key": "{secret}"',
                   headers={**admin, "Content-Type": "application/json"})
    assert r.status_code == 422
    _no_echo(r, secret)


def test_s2_14_a_validation_error_elsewhere_drops_input_and_ctx_too(client, admin, project):
    secret = new_key()
    r = client.put(f"{base(project)}/systems/card_agent", json={"provider": ["x", secret], "model": {"nested": secret}},
                   headers=admin)
    assert r.status_code == 422
    _no_echo(r, secret)


def test_s5_7_a_put_that_is_not_json_changes_nothing(client, admin, project):
    secret = new_key()
    r = client.put(f"{base(project)}/providers/openai", content=json.dumps({"api_key": secret}),
                   headers={**admin, "Content-Type": "text/plain"})
    assert 400 <= r.status_code < 500
    assert secret not in r.text
    assert provider_entry(client, project, admin, "openai")["has_key"] is False


def test_s5_7_the_platform_has_no_cors_middleware(client):
    from platform_service.app import app

    assert not any("CORS" in type(m.cls).__name__ or "CORS" in getattr(m.cls, "__name__", "")
                   for m in app.user_middleware)
    r = client.options("/projects/x/llm/providers/openai",
                       headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "PUT"})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


# ── S2.15 the models route ───────────────────────────────────────────────────


def test_s2_15_models_are_listed_live_with_the_stored_key(client, admin, project, fake, cat, monkeypatch):
    monkeypatch.setitem(cat.MODELS_URL, "openai", fake.url + "/v1/models")
    fake.reply("/v1/models", {"data": [{"id": "gpt-b"}, {"id": "gpt-a"}]})
    key = new_key()
    put_provider(client, project, "openai", admin, api_key=key)
    r = client.get(f"{base(project)}/providers/openai/models", headers=admin)
    assert r.status_code == 200
    assert r.json() == {"models": ["gpt-a", "gpt-b"], "error": None}
    assert fake.seen("/v1/models")[0].header("Authorization") == f"Bearer {key}"
    assert key not in r.text


def test_s2_15_a_failing_provider_is_200_with_an_error(client, admin, project, fake, cat, monkeypatch):
    monkeypatch.setitem(cat.MODELS_URL, "openai", fake.url + "/v1/models")
    fake.reply("/v1/models", {"error": "UPSTREAM"}, status=500)
    put_provider(client, project, "openai", admin, api_key=new_key())
    r = client.get(f"{base(project)}/providers/openai/models", headers=admin)
    assert r.status_code == 200
    assert r.json()["models"] == [] and r.json()["error"].endswith("answered HTTP 500")


def test_s2_15_a_provider_that_is_not_usable_is_409(client, admin, project):
    assert client.get(f"{base(project)}/providers/openai/models", headers=admin).status_code == 409
    assert client.get(f"{base(project)}/providers/compatible/models", headers=admin).status_code == 409


def test_s2_15_an_unknown_provider_is_404(client, admin, project):
    r = client.get(f"{base(project)}/providers/telepathy/models", headers=admin)
    assert r.status_code == 404
    assert r.json()["detail"] != "Not Found", "the route itself is missing"


def test_s2_15_ollama_lists_from_the_stored_base_url(client, admin, project, fake):
    fake.reply("/api/tags", {"models": [{"name": "gemma3"}]})
    put_provider(client, project, "ollama", admin, base_url=fake.url)
    r = client.get(f"{base(project)}/providers/ollama/models", headers=admin)
    assert r.json() == {"models": ["gemma3"], "error": None}


# ── S2.20 and S2.21 the per-system choice ────────────────────────────────────


def test_s2_20_a_choice_is_saved_and_shown(client, admin, project, fake, cat, monkeypatch):
    monkeypatch.setitem(cat.MODELS_URL, "openai", fake.url + "/v1/models")
    put_provider(client, project, "openai", admin, api_key=new_key())
    r = put_system(client, project, "card_agent", admin, "openai", "a-model-no-list-mentions")
    assert r.status_code == 200, r.text
    assert r.json() == {"system": "card_agent", "provider": "openai", "model": "a-model-no-list-mentions"}
    assert fake.requests == []  # D6: the model is not checked against the live list
    systems = {s["id"]: s for s in client.get(base(project), headers=admin).json()["systems"]}
    assert systems["card_agent"]["choice"] == {"provider": "openai", "model": "a-model-no-list-mentions"}
    assert systems["risk_mapper"]["choice"] is None


def test_s2_20_an_unknown_system_is_404(client, admin, project):
    r = put_system(client, project, "telepathy", admin, "ollama", "gemma3")
    assert r.status_code == 404
    assert r.json()["detail"] != "Not Found", "the route itself is missing"


@pytest.mark.parametrize("provider, model", [
    ("telepathy", "m"), ("openai", "gpt-4o"), ("compatible", "m"),
    ("ollama", ""), ("ollama", "   "), ("ollama", "m" * 201), ("ollama", "gem\nma"), ("ollama", "gem\x00ma"),
])
def test_s2_20_an_unusable_provider_or_bad_model_is_422(client, admin, project, provider, model):
    r = put_system(client, project, "card_agent", admin, provider, model)
    assert r.status_code == 422, (provider, model, r.text)
    systems = {s["id"]: s for s in client.get(base(project), headers=admin).json()["systems"]}
    assert systems["card_agent"]["choice"] is None


def test_s2_20_choosing_ollama_makes_its_keyless_row(client, admin, project, dsn):
    assert put_system(client, project, "risk_mapper", admin, "ollama", "llama3.2:1b").status_code == 200
    found = rows(dsn, project)
    assert [(r["provider"], r["ciphertext"], r["base_url"]) for r in found] == [("ollama", None, None)]


def test_s2_21_removing_a_choice_goes_back_to_the_environment(client, admin, project):
    put_system(client, project, "card_agent", admin, "ollama", "gemma3")
    r = client.delete(f"{base(project)}/systems/card_agent", headers=admin)
    assert r.status_code == 204
    systems = {s["id"]: s for s in client.get(base(project), headers=admin).json()["systems"]}
    assert systems["card_agent"]["choice"] is None
    assert client.delete(f"{base(project)}/systems/card_agent", headers=admin).status_code == 404


# ── S2.22 to S2.26 and S5.5 the internal resolve route ───────────────────────


def test_s2_22_the_project_must_be_a_pid(client, project):
    assert resolve(client, project["slug"]).status_code == 422


def test_s2_22_an_unknown_system_or_project_is_404(client, project):
    assert resolve(client, project["pid"]).status_code == 200  # the route exists
    for r in (resolve(client, project["pid"], system="telepathy"),
              resolve(client, "3f2b8c1e-0d4a-4e7b-9a55-000000000000")):
        assert r.status_code == 404
        assert r.json()["detail"] != "Not Found", "the route itself is missing"


def test_s2_23_s5_5_a_missing_or_wrong_token_is_401(client, project):
    assert resolve(client, project["pid"], token=None).status_code == 401
    assert resolve(client, project["pid"], token="wrong").status_code == 401
    assert resolve(client, project["pid"], token=INTERNAL_TOKEN + "x").status_code == 401


@pytest.mark.parametrize("value", [None, ""])
def test_s2_23_without_platform_internal_token_the_route_is_closed(client, project, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("PLATFORM_INTERNAL_TOKEN")
    else:
        monkeypatch.setenv("PLATFORM_INTERNAL_TOKEN", value)
    assert resolve(client, project["pid"], token="").status_code == 503
    assert resolve(client, project["pid"], token="anything").status_code == 503


def test_s2_23_the_token_is_compared_in_constant_time():
    from platform_service import app as app_module

    source = inspect.getsource(app_module)
    for name in ("llm_store", "llm_catalogue"):
        try:
            source += inspect.getsource(importlib.import_module(f"platform_service.{name}"))
        except ImportError:
            pass
    assert "compare_digest" in source and "PLATFORM_INTERNAL_TOKEN" in source


@pytest.mark.parametrize("header", ["X-Forwarded-For", "X-Forwarded-Host"])
def test_s2_24_s5_5_a_request_that_came_through_caddy_is_404(client, project, header):
    assert resolve(client, project["pid"]).status_code == 200  # the same call, not forwarded
    r = resolve(client, project["pid"], headers={header: "203.0.113.9"})
    assert r.status_code == 404


def test_s2_25_no_choice_is_not_configured(client, project):
    r = resolve(client, project["pid"])
    assert r.status_code == 200, r.text
    assert r.json() == {"configured": False}


def test_s2_25_s5_1_a_choice_resolves_with_its_decrypted_key(client, admin, project):
    key = new_key()
    put_provider(client, project, "openai", admin, api_key=key)
    put_system(client, project, "card_agent", admin, "openai", "gpt-4o-mini")
    r = resolve(client, project["pid"])
    assert r.status_code == 200, r.text
    assert r.json() == {"configured": True, "provider": "openai", "model": "gpt-4o-mini",
                        "base_url": None, "api_key": key}
    assert resolve(client, project["pid"], "risk_mapper").json() == {"configured": False}


def test_s2_25_ollama_resolves_with_the_default_base_url_and_no_key(client, admin, project):
    put_system(client, project, "risk_mapper", admin, "ollama", "llama3.2:1b")
    assert resolve(client, project["pid"], "risk_mapper").json() == {
        "configured": True, "provider": "ollama", "model": "llama3.2:1b",
        "base_url": "http://host.docker.internal:11434", "api_key": None}


def test_s2_25_compatible_resolves_with_its_stored_base_url(client, admin, project):
    key = new_key()
    put_provider(client, project, "compatible", admin, api_key=key, base_url="http://127.0.0.1:9/v1")
    put_system(client, project, "card_agent", admin, "compatible", "local")
    assert resolve(client, project["pid"]).json() == {
        "configured": True, "provider": "compatible", "model": "local",
        "base_url": "http://127.0.0.1:9/v1", "api_key": key}


def test_s2_25_a_choice_whose_key_is_gone_is_409_naming_the_provider(client, admin, project, dsn):
    key = new_key()
    put_provider(client, project, "openai", admin, api_key=key)
    put_system(client, project, "card_agent", admin, "openai", "gpt-4o-mini")
    run_sql(dsn, project, "update llm.provider set ciphertext = null where provider = 'openai'")
    r = resolve(client, project["pid"])
    assert r.status_code == 409
    assert "openai" in r.json()["detail"] and key not in r.text


def test_s2_26_the_resolve_answer_is_not_cached(client, project):
    assert resolve(client, project["pid"]).headers.get("cache-control") == "no-store"


# ── S2.6 and S5.1 write-only, S5.3 logs, S5.4 isolation ──────────────────────


def test_s2_6_s5_1_no_page_facing_response_holds_the_key_or_its_ciphertext(client, admin, project, dsn, fake, cat,
                                                                          monkeypatch):
    monkeypatch.setitem(cat.MODELS_URL, "openai", fake.url + "/v1/models")
    fake.reply("/v1/models", {"data": [{"id": "gpt-a"}]})
    key = new_key()
    bodies = [put_provider(client, project, "openai", admin, api_key=key).text]
    bodies.append(put_provider(client, project, "compatible", admin, api_key=key,
                               base_url="http://127.0.0.1:9/v1").text)
    token = rows(dsn, project, "select ciphertext from llm.provider where provider='openai'")[0]["ciphertext"]
    bodies.append(client.get(base(project), headers=admin).text)
    bodies.append(client.get(f"{base(project)}/providers/openai/models", headers=admin).text)
    bodies.append(put_system(client, project, "card_agent", admin, "openai", "gpt-a").text)
    bodies.append(client.delete(f"{base(project)}/providers/compatible", headers=admin).text)
    for text in bodies:
        assert key not in text and key[-12:] not in text
        assert token not in text and token[:20] not in text and token[-20:] not in text


def test_s5_3_no_key_reaches_the_logs(client, admin, project, fake, cat, monkeypatch, caplog):
    monkeypatch.setitem(cat.MODELS_URL, "openai", fake.url + "/v1/models")
    fake.reply("/v1/models", {"error": "x"}, status=401)
    key = new_key()
    with caplog.at_level(logging.DEBUG):
        for name in ("", "httpx", "httpcore", "urllib3", "platform_service", "uvicorn", "fastapi"):
            logging.getLogger(name).setLevel(logging.DEBUG)
        put_provider(client, project, "openai", admin, api_key=key)
        put_provider(client, project, "openai", admin, api_key=key + " x")   # 422 path
        client.get(f"{base(project)}/providers/openai/models", headers=admin)
        put_system(client, project, "card_agent", admin, "openai", "gpt-a")
        resolve(client, project["pid"])
    assert key not in caplog.text


def test_s5_4_a_key_of_one_project_is_nothing_in_another(client, admin, as_user, unique, project):
    other = client.post("/projects", json={"name": unique("llm-q")}, headers=as_user(ALICE)).json()
    key = new_key()
    put_provider(client, project, "openai", admin, api_key=key)
    put_system(client, project, "card_agent", admin, "openai", "gpt-a")
    assert provider_entry(client, other, admin, "openai")["has_key"] is False
    assert client.get(f"{base(other)}/providers/openai/models", headers=admin).status_code == 409
    r = resolve(client, other["pid"])
    assert r.json() == {"configured": False}
    assert key not in r.text
    assert put_system(client, other, "card_agent", admin, "openai", "gpt-a").status_code == 422
