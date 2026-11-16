"""One redaction rule for every Python service: aisc_redact, held to shared vectors (redaction-cases.json) that the
copies which cannot import it run in their own suites. A value is masked by the form's secret marks and by its
shape, never a number or a boolean because of its name."""

import importlib
import importlib.util
import json
from pathlib import Path

import pytest

CASES_FILE = Path(__file__).parents[1] / "redaction-cases.json"


def _redact():
    assert importlib.util.find_spec("aisc_redact") is not None, \
        "no aisc_redact module: each service keeps its own copy of the secret rule"
    return importlib.import_module("aisc_redact")


def _cases(kind: str) -> list:
    if not CASES_FILE.is_file():
        return [{"id": "no-vectors-file"}]
    return json.loads(CASES_FILE.read_text())[kind]


def test_the_shared_vectors_exist_and_cover_text_and_ledger_values():
    assert CASES_FILE.is_file(), "no redaction-cases.json beside the package"
    cases = json.loads(CASES_FILE.read_text())
    assert cases.get("text") and cases.get("ledger")


@pytest.mark.parametrize("case", _cases("text"), ids=lambda c: c["id"])
def test_text_is_scrubbed_as_the_vectors_say(case):
    redact = _redact()
    assert CASES_FILE.is_file(), "no redaction-cases.json beside the package"
    assert redact.scrub_text(case["in"], case.get("known", [])) == case["out"]


@pytest.mark.parametrize("case", _cases("ledger"), ids=lambda c: c["id"])
def test_ledger_values_are_masked_as_the_vectors_say(case):
    redact = _redact()
    assert CASES_FILE.is_file(), "no redaction-cases.json beside the package"
    assert redact.masked_for_ledger(case["in"], case.get("secret_paths", [])) == case["out"]


def test_the_mark_is_the_one_the_services_show_today():
    assert _redact().REDACTED == "[redacted]"


def test_a_number_named_like_a_secret_stays():
    assert _redact().masked_for_ledger({"tokens": 512, "max_tokens": 512, "use_key": True}) == \
        {"tokens": 512, "max_tokens": 512, "use_key": True}


def test_a_known_secret_is_taken_out_of_bytes():
    out = _redact().without_known_bytes(b"key=fake-secret-0123456789 end", ["fake-secret-0123456789"])
    assert b"fake-secret-0123456789" not in out


def test_a_shown_error_is_scrubbed_and_cut_to_its_limit():
    out = _redact().shown_error("failed with api_key=fake-0123456789abcdef " + "x" * 500, 120)
    assert "fake-0123456789abcdef" not in out and len(out) <= 120
