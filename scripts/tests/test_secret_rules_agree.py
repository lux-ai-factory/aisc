"""The secret rule lives in three packages that must not import each other: the engine's backend
(aisc_backend/config_secrets.py), the platform (platform_service/ledger/config_secrets.py) and the worker
(aisc_eval/scrub.py). Each is loaded here by its file path, with no package import, and the three are held equal:
the same patterns, the same answers on shared inputs, and a shape rule that finds whatever the platform
registry refuses, a bare `Token` or `Basic` credential included."""

import importlib.util
import json
import re
import sys

import pytest

from conftest import ROOT

FILES = {
    "backend": ROOT / "apps/backend/aisc_backend/config_secrets.py",
    "platform": ROOT / "platform/platform_service/ledger/config_secrets.py",
    "eval": ROOT / "apps/eval/aisc_eval/scrub.py",
}
REGISTRY = ROOT / "platform/platform_service/ledger/registry.py"

PEM = ("-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAx1abcDEF0123456789\nabcDEF0123456789+/ghiJKL\n"
       "-----END RSA PRIVATE KEY-----")
LEDGER_INPUTS = [
    {"api_key": "abc123", "max_tokens": 512, "nested": {"auth_token": "", "items": [{"password": None}]},
     "prompt": "use sk-abcdefghijklmnopqrst1234 ok", "note": "x"},
    {"api_key": "set", "judge_api_key": "lb-judge-0123456789abcdef", "max_tokens": 512, "list": [{"token": "abcdef"}],
     "keys": ["a"], "note": "Bearer abcDEF0123456789ghi"},
    {"api_keys": {"openai": "lb-judge-0123456789abcdef"}, "credentials": [{"user": "u", "pass": "pw-0123456789"}],
     "languages": ["en"]},
    {"base_url": "https://user:pw-0123456789@llm.example/v1", "auth": {"header": "Authorization: Token abcdef0123456789"},
     "cert": PEM, "endpoint": "https://llm.example/v1"},
    {"headers": {"Authorization": "Token abcdef0123456789", "Proxy-Authorization": "Basic dXNlcjpwYXNzd29yZA==",
                 "x-api-key": "k-0123456789", "COOKIE": "session=abc123", "Accept": "application/json"}},
    {"prompt": "call the judge with api_key=lb-judge-0123456789abcdef please", "system": "be fair",
     "note": "set judge_api_key=lb-judge-0123456789abcdef and DB_PASSWORD=hunter22xyz first"},
    {"text": "She was the bearer of bad news", "help": "Enter your password: it must contain a digit"},
]
TEXT_INPUTS = [
    ("connect failed: Authorization: Bearer abcDEF0123456789ghiJKL api_key=sk-abcdefghijklmnopqrstuvwx password: 'hunter22' "
     "token-xyz MYSECRETVALUE123", ["MYSECRETVALUE123", "short"]),
    ("hf_abcdefghijklmnopqrstuvwx ghp_abcdefghijklmnopqrstuvwxyz AKIAABCDEFGHIJKLMNOP xoxb-1234567890-abc AIza"
     + "A" * 35, []),
    ("", []),
    ("plain error: unexpected token: }", []),
    ("connect to postgresql://admin:s3cret-Pass_99@db.example:5432/app failed", []),
    ("sent Authorization: Basic dXNlcjpwYXNzd29yZA== and authorization: Token abcdef0123456789", []),
    ("GET /v1/models?api_key%3Dabcd1234efgh5678 body: password%3dhunter22xyz", []),
    ("token=abcd1234efgh5678 pwd=hunter22x aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", []),
    ("password = 'correct horse battery' next", []),
    ("key:\n" + PEM + "\ndone", []),
    ("judge_api_key=lb-judge-0123456789abcdef DB_PASSWORD=hunter22xyz OPENAI_API_KEY=abcd1234efgh5678ijkl "
     'judgeApiKey=lb-judge-0123456789abcdef {"judgeApiKey": "lb-judge-0123456789abcdef"}', []),
    ("She was the bearer of bad news. Enter your password: it must contain a digit. INFO token=EOF reached", []),
    ('password="Tr0ub4dor&3x" and password=hunter22x next', []),
]


def load(name, path):
    if not path.exists():
        pytest.fail(f"{path.relative_to(ROOT)} does not exist")
    spec = importlib.util.spec_from_file_location(f"secret_rule_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module                      # dataclasses look their module up while it loads
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def copies():
    return {name: load(name, path) for name, path in FILES.items()}


def test_the_three_copies_have_the_same_patterns(copies):
    shapes = {(m.SECRET_SHAPE.pattern, m.SECRET_SHAPE.flags) for m in copies.values()}
    names = {(m.LEDGER_SECRET_NAME.pattern, m.LEDGER_SECRET_NAME.flags) for m in copies.values()}
    assert len(shapes) == 1, shapes
    assert len(names) == 1, names


@pytest.mark.parametrize("value", LEDGER_INPUTS, ids=["masked", "paths", "nested", "new_shapes",
                                                       "header_fields", "assignments_in_text", "benign"])
def test_the_backend_and_the_platform_mask_ledger_copies_alike(copies, value):
    backend, platform = copies["backend"], copies["platform"]
    assert backend.masked_for_ledger(value) == platform.masked_for_ledger(value)
    assert backend.plaintext_secret_paths(value) == platform.plaintext_secret_paths(value)


@pytest.mark.parametrize("text, known", TEXT_INPUTS, ids=["failure", "shapes", "empty", "plain", "url_credentials",
                                                         "authorization", "url_encoded", "bare_names", "quoted",
                                                         "private_key", "prefixed_names", "benign",
                                                         "password_values"])
def test_the_backend_and_the_worker_scrub_text_alike(copies, text, known):
    assert copies["backend"].scrub_text(text, known) == copies["eval"].scrub_text(text, known)


def test_the_shape_rule_finds_whatever_the_registry_refuses(copies):
    registry = load("registry", REGISTRY)
    for module in copies.values():
        # a Bearer, Basic or Token value counts only when it looks like a credential (16 characters or more),
        # in an Authorization header or on its own
        for value in ["Bearer " + "a" * 16, "sk-" + "a" * 16, "eyJa.b.c", "Authorization: Basic " + "a" * 16,
                      "Authorization: Token " + "a" * 16, "Basic " + "a" * 16, "Token " + "a" * 16,
                      "basic " + "a" * 16, "token " + "a" * 16, "send Token " + "a" * 16 + " now"]:
            assert registry._SECRET.search(value), value
            assert module.SECRET_SHAPE.search(value), value


# A bare Token or Basic credential, with no Authorization header in front

#: (text, credential): plain, lowercase and mid-sentence forms, each with a credential-shaped value of 16+ characters
BARE_CREDENTIALS = [
    ("Token abcdef0123456789", "abcdef0123456789"),
    ("Basic dXNlcjpwYXNzd29yZDEyMzQ=", "dXNlcjpwYXNzd29yZDEyMzQ="),
    ("token abcdef0123456789abcd", "abcdef0123456789abcd"),
    ("basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==", "QWxhZGRpbjpvcGVuIHNlc2FtZQ=="),
    ("call it with Token abcDEF0123456789xyz and wait", "abcDEF0123456789xyz"),
    ("send basic QWxhZGRpbjpvcGVuIHNlc2FtZQ== here", "QWxhZGRpbjpvcGVuIHNlc2FtZQ=="),
]
BARE_IDS = ["token", "basic", "lowercase_token", "lowercase_basic", "token_mid_sentence", "basic_mid_sentence"]
#: Token and Basic in prose, or before a value too short to be a credential (15 characters)
BARE_BENIGN = ["Please accept a token of thanks.", "Token abc", "Basic abc", "Basic training starts on Monday.",
               "Token abcdef012345678"]
BENIGN_IDS = ["token_in_prose", "short_token", "short_basic", "basic_in_prose", "fifteen_characters"]


@pytest.mark.parametrize("name", sorted(FILES))
@pytest.mark.parametrize("text, credential", BARE_CREDENTIALS, ids=BARE_IDS)
def test_every_copy_finds_a_bare_token_or_basic_credential(copies, name, text, credential):
    assert copies[name].SECRET_SHAPE.search(text), (name, text)


@pytest.mark.parametrize("name", ["backend", "eval"])
@pytest.mark.parametrize("text, credential", BARE_CREDENTIALS, ids=BARE_IDS)
def test_the_text_rule_redacts_a_bare_token_or_basic_credential(copies, name, text, credential):
    module = copies[name]
    scrubbed = module.scrub_text(text)
    assert credential not in scrubbed, (name, scrubbed)
    assert module.REDACTED in scrubbed, (name, scrubbed)
    if text.startswith("call it with "):
        assert scrubbed.startswith("call it with ") and scrubbed.endswith(" and wait"), scrubbed
    if text.startswith("send "):
        assert scrubbed.startswith("send ") and scrubbed.endswith(" here"), scrubbed


@pytest.mark.parametrize("name", ["backend", "platform"])
@pytest.mark.parametrize("text, credential", BARE_CREDENTIALS, ids=BARE_IDS)
def test_the_ledger_copy_hides_a_bare_token_or_basic_credential(copies, name, text, credential):
    module = copies[name]
    assert module.masked_for_ledger({"text": text}) == {"text": module.SECRET_SET}
    assert module.plaintext_secret_paths({"text": text}) == ["text"]


@pytest.mark.parametrize("name", sorted(FILES))
@pytest.mark.parametrize("text", BARE_BENIGN, ids=BENIGN_IDS)
def test_token_or_basic_in_prose_or_before_a_short_value_is_left_alone(copies, name, text):
    module = copies[name]
    assert not module.SECRET_SHAPE.search(text), (name, text)
    if hasattr(module, "scrub_text"):
        assert module.scrub_text(text) == text
    if hasattr(module, "masked_for_ledger"):
        assert module.masked_for_ledger({"text": text}) == {"text": text}
        assert module.plaintext_secret_paths({"text": text}) == []


def test_the_backend_and_the_worker_have_the_same_assignment_rule(copies):
    assert (copies["backend"].SECRET_ASSIGNMENT.pattern, copies["backend"].SECRET_ASSIGNMENT.flags) == (
        copies["eval"].SECRET_ASSIGNMENT.pattern, copies["eval"].SECRET_ASSIGNMENT.flags)


@pytest.mark.parametrize("name", sorted(FILES))
def test_each_copy_says_what_the_rule_does_not_catch(name):
    source = FILES[name].read_text()
    assert "base64" in source
    assert re.search(r"(split|broken) across lines", source)


# Header fields and assignments in text, in both ledger-copy rules

@pytest.mark.parametrize("name", ["backend", "platform"])
def test_both_ledger_copies_hide_header_fields_and_assignments_in_text(copies, name):
    module = copies[name]
    headers, text = LEDGER_INPUTS[4], LEDGER_INPUTS[5]
    masked = module.masked_for_ledger(headers)["headers"]
    assert masked == {"Authorization": "set", "Proxy-Authorization": "set", "x-api-key": "set", "COOKIE": "set",
                      "Accept": "application/json"}
    assert module.plaintext_secret_paths(headers) == [
        "headers.Authorization", "headers.Proxy-Authorization", "headers.x-api-key", "headers.COOKIE"]
    masked_text = module.masked_for_ledger(text)
    for secret in ("lb-judge-0123456789abcdef", "hunter22xyz"):
        assert secret not in json.dumps(masked_text), name
    assert masked_text["system"] == "be fair"
    assert module.plaintext_secret_paths(text) == ["prompt", "note"]
    assert module.masked_for_ledger(masked_text) == masked_text
