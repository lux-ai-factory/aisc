"""The provider catalogue and the live model listers (01-specs.md S2.3, S2.15 to S2.19, S5.3, S5.6, S5.8).

No database. Every provider call goes to a fake server on 127.0.0.1; the hosted URLs
are constants in `llm_catalogue.MODELS_URL`, monkeypatched per test (S2.18).

Interface pinned by these tests (stage 2 decision, see 02-tests.md):
  llm_catalogue.PROVIDERS[id]    -> entry with label, key_required, base_url_editable, lister
  llm_catalogue.MODELS_URL[id]   -> the listing URL of each hosted provider (not ollama/compatible)
  llm_catalogue.list_models(provider, api_key=None, base_url=None) -> {"models": [...], "error": str|None}
The module is imported inside a fixture, so a missing module fails each test instead of
stopping the whole suite at collection.
"""
from __future__ import annotations

import importlib
import json
import logging

import pytest

from tests.llm_support import FakeServer, closed_port_url, field_of, new_key

IDS = {"anthropic", "compatible", "deepseek", "google", "groq", "meta", "mistral",
       "ollama", "openai", "openrouter", "qwen", "together", "xai"}
KEYLESS = {"ollama", "compatible"}

#: S2.19, the listing URL of each hosted provider
REAL_URLS = {
    "openai": "https://api.openai.com/v1/models",
    "anthropic": "https://api.anthropic.com/v1/models",
    "mistral": "https://api.mistral.ai/v1/models",
    "deepseek": "https://api.deepseek.com/models",
    "google": "https://generativelanguage.googleapis.com/v1beta/models",
    "groq": "https://api.groq.com/openai/v1/models",
    "meta": "https://api.llama.com/compat/v1/models",
    "openrouter": "https://openrouter.ai/api/v1/models",
    "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/models",
    "together": "https://api.together.xyz/v1/models",
    "xai": "https://api.x.ai/v1/models",
}
BEARER_DATA = ["openai", "deepseek", "groq", "meta", "openrouter", "qwen", "xai"]
MARKER = "UPSTREAM-BODY-MARKER-7f3a"


@pytest.fixture
def cat():
    return importlib.import_module("platform_service.llm_catalogue")


@pytest.fixture
def fake():
    server = FakeServer()
    yield server
    server.close()


def label(cat, provider):
    return field_of(cat.PROVIDERS[provider], "label")


def point(cat, monkeypatch, provider, fake, path="/v1/models"):
    """Point a hosted provider's constant at the fake server; returns the path it serves."""
    monkeypatch.setitem(cat.MODELS_URL, provider, fake.url + path)
    return path


# ── S2.3 the catalogue ───────────────────────────────────────────────────────


def test_s2_3_the_catalogue_is_exactly_the_agents_thirteen_providers(cat):
    assert set(cat.PROVIDERS) == IDS


def test_s2_3_every_entry_has_a_label_and_the_two_flags(cat):
    for pid, entry in cat.PROVIDERS.items():
        assert isinstance(field_of(entry, "label"), str) and field_of(entry, "label").strip(), pid
        assert field_of(entry, "key_required") is (pid not in KEYLESS), pid
        assert field_of(entry, "base_url_editable") is (pid in KEYLESS), pid
        assert field_of(entry, "lister"), pid


def test_s2_18_s2_19_each_hosted_provider_lists_from_its_constant_documented_url(cat):
    assert dict(cat.MODELS_URL) == REAL_URLS


def test_s2_18_no_env_variable_overrides_a_hosted_url(cat, monkeypatch, fake):
    for name in ("OPENAI_BASE_URL", "PLATFORM_OPENAI_MODELS_URL", "BAF_LLM_BASE_URL"):
        monkeypatch.setenv(name, fake.url)
    importlib.reload(cat)
    assert cat.MODELS_URL["openai"] == REAL_URLS["openai"]


# ── S2.19 the request each lister makes ──────────────────────────────────────


@pytest.mark.parametrize("provider", BEARER_DATA)
def test_s2_19_openai_style_providers_send_a_bearer_key_and_read_data_ids(cat, monkeypatch, fake, provider):
    path = point(cat, monkeypatch, provider, fake)
    fake.reply(path, {"object": "list", "data": [{"id": "m-b"}, {"id": "m-a"}]})
    key = new_key()
    got = cat.list_models(provider, api_key=key)
    assert got == {"models": ["m-a", "m-b"], "error": None}
    assert fake.seen(path)[0].header("Authorization") == f"Bearer {key}"


def test_s2_19_anthropic_uses_x_api_key_and_pages_by_after_id(cat, monkeypatch, fake):
    path = point(cat, monkeypatch, "anthropic", fake)

    def pages(seen):
        from tests.llm_support import Canned
        after = (seen.query.get("after_id") or [None])[0]
        if after is None:
            body = {"data": [{"id": "claude-a"}, {"id": "claude-b"}], "has_more": True, "last_id": "claude-b"}
        else:
            body = {"data": [{"id": "claude-c"}], "has_more": False, "last_id": "claude-c"}
        return Canned(200, json.dumps(body).encode())

    fake.reply(path, pages)
    key = new_key()
    got = cat.list_models("anthropic", api_key=key)
    assert got == {"models": ["claude-a", "claude-b", "claude-c"], "error": None}
    first, second = fake.seen(path)
    assert first.query.get("limit") == ["1000"]
    assert second.query.get("after_id") == ["claude-b"]
    for r in (first, second):
        assert r.header("x-api-key") == key
        assert r.header("anthropic-version") == "2023-06-01"
        assert r.header("Authorization") is None


def test_s2_19_mistral_keeps_only_chat_models_when_capabilities_are_given(cat, monkeypatch, fake):
    path = point(cat, monkeypatch, "mistral", fake)
    fake.reply(path, {"data": [
        {"id": "mistral-large-latest", "capabilities": {"completion_chat": True}},
        {"id": "mistral-embed", "capabilities": {"completion_chat": False}},
        {"id": "no-capabilities-listed"},
    ]})
    key = new_key()
    got = cat.list_models("mistral", api_key=key)
    assert got["models"] == ["mistral-large-latest", "no-capabilities-listed"]
    assert fake.seen(path)[0].header("Authorization") == f"Bearer {key}"


def test_s2_19_google_uses_its_header_never_the_query_and_strips_the_prefix(cat, monkeypatch, fake):
    path = point(cat, monkeypatch, "google", fake, "/v1beta/models")

    def pages(seen):
        from tests.llm_support import Canned
        token = (seen.query.get("pageToken") or [None])[0]
        if token is None:
            body = {"models": [
                {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]},
            ], "nextPageToken": "tok-2"}
        else:
            body = {"models": [
                {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["countTokens", "generateContent"]},
            ]}
        return Canned(200, json.dumps(body).encode())

    fake.reply(path, pages)
    key = new_key()
    got = cat.list_models("google", api_key=key)
    assert got == {"models": ["gemini-2.5-flash", "gemini-2.5-pro"], "error": None}
    first, second = fake.seen(path)
    assert first.query.get("pageSize") == ["1000"]
    assert second.query.get("pageToken") == ["tok-2"]
    for r in (first, second):
        assert r.header("x-goog-api-key") == key
        assert "key" not in r.query
        assert key not in json.dumps(r.query)


def test_s2_19_together_reads_a_top_level_list_of_chat_and_language_models(cat, monkeypatch, fake):
    path = point(cat, monkeypatch, "together", fake)
    fake.reply(path, [
        {"id": "meta-llama/Llama-3-70b", "type": "chat"},
        {"id": "base-model", "type": "language"},
        {"id": "an-embedder", "type": "embedding"},
        {"id": "untyped"},
    ])
    got = cat.list_models("together", api_key=new_key())
    assert got["models"] == ["base-model", "meta-llama/Llama-3-70b", "untyped"]


def test_s2_19_ollama_lists_tags_under_the_base_url_without_v1_and_without_auth(cat, fake):
    fake.reply("/api/tags", {"models": [{"name": "llama3.2:1b"}, {"name": "gemma3"}]})
    got = cat.list_models("ollama", base_url=fake.url + "/v1")
    assert got == {"models": ["gemma3", "llama3.2:1b"], "error": None}
    r = fake.seen("/api/tags")[0]
    assert r.header("Authorization") is None


def test_s2_19_compatible_lists_base_url_models_with_a_bearer_when_a_key_is_stored(cat, fake):
    fake.reply("/v1/models", {"data": [{"id": "local-a"}]})
    key = new_key()
    assert cat.list_models("compatible", api_key=key, base_url=fake.url + "/v1")["models"] == ["local-a"]
    assert fake.seen("/v1/models")[0].header("Authorization") == f"Bearer {key}"


def test_s2_19_compatible_without_a_key_sends_no_authorization_and_accepts_a_bare_list(cat, fake):
    fake.reply("/v1/models", [{"id": "local-b"}, {"id": "local-a"}])
    assert cat.list_models("compatible", base_url=fake.url + "/v1")["models"] == ["local-a", "local-b"]
    assert fake.seen("/v1/models")[0].header("Authorization") is None


# ── S2.17 bounds ─────────────────────────────────────────────────────────────


def test_s2_17_ids_are_deduplicated_sorted_and_bad_ones_dropped(cat, monkeypatch, fake):
    path = point(cat, monkeypatch, "openai", fake)
    fake.reply(path, {"data": [{"id": "b"}, {"id": "a"}, {"id": "b"}, {"id": ""}, {"id": 42},
                               {"id": None}, {"id": "x" * 201}, {"id": "y" * 200}, {"nothing": 1}]})
    assert cat.list_models("openai", api_key=new_key())["models"] == ["a", "b", "y" * 200]


def test_s2_17_at_most_5000_ids_are_kept(cat, monkeypatch, fake):
    path = point(cat, monkeypatch, "openai", fake)
    fake.reply(path, {"data": [{"id": f"m-{n:05d}"} for n in range(6000)]})
    got = cat.list_models("openai", api_key=new_key())
    assert got["error"] is None
    assert len(got["models"]) == 5000


def test_s2_17_at_most_ten_pages_are_fetched(cat, monkeypatch, fake):
    path = point(cat, monkeypatch, "anthropic", fake)
    counter = {"n": 0}

    def endless(seen):
        from tests.llm_support import Canned
        counter["n"] += 1
        n = counter["n"]
        return Canned(200, json.dumps({"data": [{"id": f"c-{n}"}], "has_more": True, "last_id": f"c-{n}"}).encode())

    fake.reply(path, endless)
    cat.list_models("anthropic", api_key=new_key())
    assert len(fake.seen(path)) <= 10


def test_s2_17_a_page_over_5_mb_is_not_a_model_list(cat, monkeypatch, fake):
    path = point(cat, monkeypatch, "openai", fake)
    big = json.dumps({"data": [{"id": "m"}], "pad": "x" * (5 * 1024 * 1024 + 10)}).encode()
    fake.reply(path, raw=big)
    got = cat.list_models("openai", api_key=new_key())
    assert got["models"] == []
    assert got["error"] == f"{label(cat, 'openai')} did not send a model list"


def test_s2_17_s5_6_redirects_are_not_followed_so_the_key_stays_with_the_provider(cat, monkeypatch, fake):
    elsewhere = FakeServer()
    try:
        elsewhere.reply("/v1/models", {"data": [{"id": "stolen"}]})
        path = point(cat, monkeypatch, "openai", fake)
        fake.reply(path, raw=b"", status=302, headers={"Location": elsewhere.url + "/v1/models"})
        got = cat.list_models("openai", api_key=new_key())
        assert elsewhere.requests == []
        assert got["models"] == []
        assert got["error"] == f"{label(cat, 'openai')} answered HTTP 302"
    finally:
        elsewhere.close()


def test_s2_17_s2_16_a_slow_provider_times_out_with_a_fixed_message(cat, monkeypatch, fake):
    monkeypatch.setenv("PLATFORM_LLM_LIST_TIMEOUT", "1")
    path = point(cat, monkeypatch, "openai", fake)
    fake.reply(path, {"data": []}, delay=3.0)
    got = cat.list_models("openai", api_key=new_key())
    assert got["models"] == []
    assert got["error"] in {f"{label(cat, 'openai')} did not answer within 1 s",
                            f"{label(cat, 'openai')} did not answer within 1.0 s"}


# ── S2.16 fixed error messages, bodies never echoed ──────────────────────────


@pytest.mark.parametrize("status", [401, 403])
def test_s2_16_a_refused_key_is_named_with_its_status(cat, monkeypatch, fake, status):
    path = point(cat, monkeypatch, "openai", fake)
    fake.reply(path, {"error": MARKER}, status=status)
    got = cat.list_models("openai", api_key=new_key())
    assert got == {"models": [], "error": f"{label(cat, 'openai')} refused the key (HTTP {status})"}


@pytest.mark.parametrize("status", [400, 404, 429, 500, 503])
def test_s2_16_another_status_is_reported_without_the_body(cat, monkeypatch, fake, status):
    path = point(cat, monkeypatch, "openai", fake)
    fake.reply(path, {"error": MARKER}, status=status)
    got = cat.list_models("openai", api_key=new_key())
    assert got == {"models": [], "error": f"{label(cat, 'openai')} answered HTTP {status}"}


def test_s2_16_a_provider_that_is_down_could_not_be_reached(cat, monkeypatch):
    monkeypatch.setitem(cat.MODELS_URL, "openai", closed_port_url() + "/v1/models")
    got = cat.list_models("openai", api_key=new_key())
    assert got == {"models": [], "error": f"could not reach {label(cat, 'openai')}"}


@pytest.mark.parametrize("raw", [
    b"<html>" + MARKER.encode() + b"</html>",
    json.dumps({"data": MARKER}).encode(),
    json.dumps({"unexpected": [MARKER]}).encode(),
    json.dumps(MARKER).encode(),
])
def test_s2_16_not_json_or_the_wrong_shape_is_not_a_model_list(cat, monkeypatch, fake, raw):
    path = point(cat, monkeypatch, "openai", fake)
    fake.reply(path, raw=raw)
    got = cat.list_models("openai", api_key=new_key())
    assert got == {"models": [], "error": f"{label(cat, 'openai')} did not send a model list"}


# ── S5.3 no key in logs, S5.6 hosted keys go only to their constant URL, S5.8 SSRF bound ──


def test_s5_3_listing_never_logs_the_key_on_success_or_any_error(cat, monkeypatch, fake, caplog):
    key = new_key()
    path = point(cat, monkeypatch, "openai", fake)
    monkeypatch.setenv("PLATFORM_LLM_LIST_TIMEOUT", "1")
    answers = [
        dict(body={"data": [{"id": "ok"}]}),
        dict(body={"e": MARKER}, status=401),
        dict(body={"e": MARKER}, status=500),
        dict(raw=b"not json"),
        dict(body={"data": []}, delay=2.5),
    ]
    with caplog.at_level(logging.DEBUG):
        for logger in ("httpx", "httpcore", "urllib3", "platform_service"):
            logging.getLogger(logger).setLevel(logging.DEBUG)
        messages = []
        for answer in answers:
            fake.reply(path, **answer)
            messages.append(cat.list_models("openai", api_key=key)["error"] or "")
        monkeypatch.setitem(cat.MODELS_URL, "openai", closed_port_url() + "/v1/models")
        messages.append(cat.list_models("openai", api_key=key)["error"] or "")
    assert key not in caplog.text
    assert all(key not in m and MARKER not in m for m in messages)


def test_s5_6_a_hosted_provider_ignores_any_base_url_it_is_given(cat, monkeypatch, fake):
    elsewhere = FakeServer()
    try:
        path = point(cat, monkeypatch, "openai", fake)
        fake.reply(path, {"data": [{"id": "gpt-x"}]})
        cat.list_models("openai", api_key=new_key(), base_url=elsewhere.url + "/v1")
        assert elsewhere.requests == []
        assert len(fake.seen(path)) == 1
    finally:
        elsewhere.close()


@pytest.mark.parametrize("provider", ["ollama", "compatible"])
def test_s5_8_admin_urls_are_fetched_without_redirects_and_never_reflected(cat, fake, provider):
    elsewhere = FakeServer()
    try:
        path = "/api/tags" if provider == "ollama" else "/v1/models"
        fake.reply(path, raw=MARKER.encode(), status=301, headers={"Location": elsewhere.url + path})
        got = cat.list_models(provider, api_key=new_key() if provider == "compatible" else None,
                              base_url=fake.url + "/v1")
        assert elsewhere.requests == []
        assert got["models"] == []
        assert MARKER not in (got["error"] or "")
        assert got["error"] == f"{label(cat, provider)} answered HTTP 301"
    finally:
        elsewhere.close()


@pytest.mark.parametrize("provider", ["ollama", "compatible"])
def test_s5_8_admin_urls_get_the_same_size_bound(cat, fake, provider):
    path = "/api/tags" if provider == "ollama" else "/v1/models"
    fake.reply(path, raw=json.dumps({"pad": "x" * (5 * 1024 * 1024 + 10)}).encode())
    got = cat.list_models(provider, base_url=fake.url + "/v1")
    assert got == {"models": [], "error": f"{label(cat, provider)} did not send a model list"}
