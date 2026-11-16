"""The ledger copy rule is kept twice, in the engine's backend (aisc_backend/config_secrets.py) and in the
platform (platform_service/ledger/config_secrets.py). Both hide what a plugin form marks as secret and any value
shaped like a key, never a value for its name alone: the same inputs give the same, expected answers.

Each copy is loaded by its file path, with no package import, as test_secret_rules_agree.py loads them."""

import importlib.util
import inspect
import sys

import pytest

from conftest import ROOT

FILES = {
    "backend": ROOT / "apps/backend/aisc_backend/config_secrets.py",
    "platform": ROOT / "platform/platform_service/ledger/config_secrets.py",
}

#: (value, paths the form marks, the ledger copy)
CASES = [
    ({"tokens": 512, "max_tokens": 64}, frozenset(), {"tokens": 512, "max_tokens": 64}),
    ({"phrase": "open sesame"}, frozenset({"phrase"}), {"phrase": "set"}),
    ({"api_key": "sk-abcdefghijklmnopqrst1234", "max_tokens": 512}, frozenset(), {"api_key": "set", "max_tokens": 512}),
    ({"stop_token": "END"}, frozenset(), {"stop_token": "END"}),
]


def _load(name, path):
    if str(ROOT / "shared/identity") not in sys.path:   # both import the shared rule, aisc_redact
        sys.path.insert(0, str(ROOT / "shared/identity"))
    spec = importlib.util.spec_from_file_location(f"ledger_copy_rule_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def copies():
    return {name: _load(name, path) for name, path in FILES.items()}


@pytest.mark.parametrize("copy", list(FILES))
@pytest.mark.parametrize("value, marked, expected", CASES, ids=["token_counts", "form_marked", "shaped_key",
                                                                 "short_word"])
def test_each_copy_masks_by_form_marks_and_value_shape(copies, copy, value, marked, expected):
    rule = copies[copy].masked_for_ledger
    if marked:
        assert "secret_paths" in inspect.signature(rule).parameters, \
            f"{copy}: masked_for_ledger takes no secret_paths, so a form's marks cannot reach it"
        assert rule(value, marked) == expected
    else:
        assert rule(value) == expected
