"""The secret rule lives in three packages that must not import each other: the engine's backend
(aisc_backend/config_secrets.py), the platform (platform_service/ledger/config_secrets.py) and the worker
(aisc_eval/scrub.py). Each is loaded here by its file path, with no package import, and the three are held equal:
the same patterns, the same answers on shared inputs, and a shape rule that finds whatever the platform
registry refuses."""

import importlib.util
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
     "keys": ["a"], "note": "Bearer abc"},
    {"api_keys": {"openai": "lb-judge-0123456789abcdef"}, "credentials": [{"user": "u", "pass": "pw-0123456789"}],
     "languages": ["en"]},
    {"base_url": "https://user:pw-0123456789@llm.example/v1", "auth": {"header": "Authorization: Token abcdef0123456789"},
     "cert": PEM, "endpoint": "https://llm.example/v1"},
]
TEXT_INPUTS = [
    ("connect failed: Authorization: Bearer abc.def.ghi api_key=sk-abcdefghijklmnopqrstuvwx password: 'hunter22' "
     "token-xyz MYSECRETVALUE123", ["MYSECRETVALUE123", "short"]),
    ("hf_abcdefghijklmnopqrstuvwx ghp_abcdefghijklmnopqrstuvwxyz AKIAABCDEFGHIJKLMNOP xoxb-1234567890-abc AIza"
     + "A" * 35, []),
    ("", []),
    ("plain error: unexpected token: }", []),
    ("connect to postgresql://admin:s3cret-Pass_99@db.example:5432/app failed", []),
    ("sent Authorization: Basic dXNlcjpwYXNzd29yZA== and authorization: Token abcdef0123456789", []),
    ("GET /v1/models?api_key%3Dabcd1234efgh5678 body: password%3dhunter22xyz", []),
    ("token=abcd1234efgh pwd=hunter22x aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", []),
    ("password = 'correct horse battery' next", []),
    ("key:\n" + PEM + "\ndone", []),
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


@pytest.mark.parametrize("value", LEDGER_INPUTS, ids=["masked", "paths", "nested", "new_shapes"])
def test_the_backend_and_the_platform_mask_ledger_copies_alike(copies, value):
    backend, platform = copies["backend"], copies["platform"]
    assert backend.masked_for_ledger(value) == platform.masked_for_ledger(value)
    assert backend.plaintext_secret_paths(value) == platform.plaintext_secret_paths(value)


@pytest.mark.parametrize("text, known", TEXT_INPUTS, ids=["failure", "shapes", "empty", "plain", "url_credentials",
                                                         "authorization", "url_encoded", "bare_names", "quoted",
                                                         "private_key"])
def test_the_backend_and_the_worker_scrub_text_alike(copies, text, known):
    assert copies["backend"].scrub_text(text, known) == copies["eval"].scrub_text(text, known)


def test_the_shape_rule_finds_whatever_the_registry_refuses(copies):
    registry = load("registry", REGISTRY)
    for module in copies.values():
        for value in ["Bearer x", "sk-" + "a" * 16, "eyJa.b.c"]:
            assert registry._SECRET.search(value), value
            assert module.SECRET_SHAPE.search(value), value


def test_the_backend_and_the_worker_have_the_same_assignment_rule(copies):
    assert (copies["backend"].SECRET_ASSIGNMENT.pattern, copies["backend"].SECRET_ASSIGNMENT.flags) == (
        copies["eval"].SECRET_ASSIGNMENT.pattern, copies["eval"].SECRET_ASSIGNMENT.flags)


@pytest.mark.parametrize("name", sorted(FILES))
def test_each_copy_says_what_the_rule_does_not_catch(name):
    source = FILES[name].read_text()
    assert "base64" in source
    assert re.search(r"(split|broken) across lines", source)
