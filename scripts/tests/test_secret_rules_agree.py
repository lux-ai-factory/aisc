"""The secret rule lives in three packages that must not import each other: the engine's backend
(aisc_backend/config_secrets.py), the platform (platform_service/ledger/config_secrets.py) and the worker
(aisc_eval/scrub.py). Each is loaded here by its file path, with no package import, and the three are held equal:
the same patterns, the same answers on shared inputs, and a shape rule that finds whatever the platform
registry refuses."""

import importlib.util
import sys

import pytest

from conftest import ROOT

FILES = {
    "backend": ROOT / "apps/backend/aisc_backend/config_secrets.py",
    "platform": ROOT / "platform/platform_service/ledger/config_secrets.py",
    "eval": ROOT / "apps/eval/aisc_eval/scrub.py",
}
REGISTRY = ROOT / "platform/platform_service/ledger/registry.py"

LEDGER_INPUTS = [
    {"api_key": "abc123", "max_tokens": 512, "nested": {"auth_token": "", "items": [{"password": None}]},
     "prompt": "use sk-abcdefghijklmnopqrst1234 ok", "note": "x"},
    {"api_key": "set", "judge_api_key": "lb-judge-0123456789abcdef", "max_tokens": 512, "list": [{"token": "abcdef"}],
     "keys": ["a"], "note": "Bearer abc"},
]
TEXT_INPUTS = [
    ("connect failed: Authorization: Bearer abc.def.ghi api_key=sk-abcdefghijklmnopqrstuvwx password: 'hunter22' "
     "token-xyz MYSECRETVALUE123", ["MYSECRETVALUE123", "short"]),
    ("hf_abcdefghijklmnopqrstuvwx ghp_abcdefghijklmnopqrstuvwxyz AKIAABCDEFGHIJKLMNOP xoxb-1234567890-abc AIza"
     + "A" * 35, []),
    ("", []),
    ("plain error: unexpected token: }", []),
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


@pytest.mark.parametrize("value", LEDGER_INPUTS, ids=["masked", "paths"])
def test_the_backend_and_the_platform_mask_ledger_copies_alike(copies, value):
    backend, platform = copies["backend"], copies["platform"]
    assert backend.masked_for_ledger(value) == platform.masked_for_ledger(value)
    assert backend.plaintext_secret_paths(value) == platform.plaintext_secret_paths(value)


@pytest.mark.parametrize("text, known", TEXT_INPUTS, ids=["failure", "shapes", "empty", "plain"])
def test_the_backend_and_the_worker_scrub_text_alike(copies, text, known):
    assert copies["backend"].scrub_text(text, known) == copies["eval"].scrub_text(text, known)


def test_the_shape_rule_finds_whatever_the_registry_refuses(copies):
    registry = load("registry", REGISTRY)
    for module in copies.values():
        for value in ["Bearer x", "sk-" + "a" * 16, "eyJa.b.c"]:
            assert registry._SECRET.search(value), value
            assert module.SECRET_SHAPE.search(value), value
