"""The Python services that cannot import aisc_identity keep a byte-identical copy of its switch parser, and
each copy passes the shared cases.

The qualification agents and the results dashboard run in images without shared/identity, so they carry
aisc_identity/switches.py as a file of their own. A copy that drifts would read AUTH_ENABLED or LEDGER_MODE
differently from every other service.

Read-only: the files are compared and the copies loaded as modules.
"""

import importlib.util
import json

import pytest

from conftest import ROOT

COPIES = ["apps/qualification/services/agents/fill/switches.py", "apps/results-dashboard/aisc_ext/switches.py"]
SOURCE = ROOT / "shared/identity/aisc_identity/switches.py"
CASES_FILE = ROOT / "shared/identity/switch-cases.json"


def _load(path):
    spec = importlib.util.spec_from_file_location("switches_copy", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("copy", COPIES)
def test_each_copy_is_the_shared_parser(copy):
    assert SOURCE.is_file(), "shared/identity/aisc_identity/switches.py does not exist"
    assert (ROOT / copy).is_file(), f"{copy} does not exist"
    assert (ROOT / copy).read_bytes() == SOURCE.read_bytes(), f"{copy} differs from the shared parser"


@pytest.mark.parametrize("copy", COPIES)
def test_each_copy_passes_the_shared_cases(copy):
    assert (ROOT / copy).is_file(), f"{copy} does not exist"
    module = _load(ROOT / copy)
    cases = json.loads(CASES_FILE.read_text())
    for case in cases["ledger_mode"]:
        env = {} if case["value"] is None else {"LEDGER_MODE": case["value"]}
        if case.get("refused"):
            with pytest.raises(module.SwitchInvalid):
                module.ledger_mode(env)
        else:
            assert module.ledger_mode(env) == case["is"]
    for case in cases["switch"]:
        if case.get("refused"):
            with pytest.raises(module.SwitchInvalid):
                module.parse_switch("AUTH_ENABLED", case["value"])
        else:
            assert module.parse_switch("AUTH_ENABLED", case["value"]) is case["is"]
