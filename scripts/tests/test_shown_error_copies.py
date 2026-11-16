"""The safe error text shown to editors is one rule, aisc_redact.shown_error. Control objectives imports it; the
qualification agents, which cannot, keep a copy (fill/errors.py) that gives the same answers on the shared vectors
(shared/identity/redaction-cases.json), here and in the agents' own suite."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
QUALIFICATION_COPY = ROOT / "apps/qualification/services/agents/fill/errors.py"
CONTROL_OBJECTIVES = ROOT / "apps/control-objectives/src/aisc_control_objectives/errors.py"
CASES = json.loads((ROOT / "shared/identity/redaction-cases.json").read_text())["shown_error"]


def _load(name: str, path: Path):
    sys.path.insert(0, str(ROOT / "shared/identity"))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_control_objectives_imports_the_shared_rule():
    assert "from aisc_redact import" in CONTROL_OBJECTIVES.read_text()


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_both_show_an_error_as_the_vectors_say(case):
    for name, path in (("qualification_errors", QUALIFICATION_COPY), ("objectives_errors", CONTROL_OBJECTIVES)):
        assert _load(name, path).shown_error(case["in"], case["limit"]) == case["out"], name
