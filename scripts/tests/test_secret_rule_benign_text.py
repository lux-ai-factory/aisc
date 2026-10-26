"""The secret rule must not eat ordinary text. The fixture `fixtures/secret_rules/benign_text.json` holds 1359
lines with no secret in them: CSV rows, log lines, JSON documents, prose with "password:", "bearer" and
"Authorization:" in it, and URLs without credentials. Every copy of the rule is measured on it:

- the text rule (`scrub_text`, backend and worker) changes fewer than 1% of the lines;
- the ledger-copy rule (`masked_for_ledger`, `holds_plaintext_secret`, backend and platform) masks fewer than 1%;
- the stored-configuration rule never rewrites a kept text field;
- the lines a false redaction was seen on stay exactly as they are, in every copy.
"""

import json

import pytest

from conftest import ROOT
from test_secret_rules_agree import FILES, load

CORPUS = json.loads((ROOT / "scripts/tests/fixtures/secret_rules/benign_text.json").read_text())
LINES = [line for kind in sorted(CORPUS) for line in CORPUS[kind]]
LIMIT = 0.01

#: Lines of the corpus that an earlier rule changed, and that must stay as they are.
UNCHANGED = [
    "She was the bearer of bad news about the model's fairness score.",
    "Rate the bearer bond risk for the following portfolio.",
    "Bearer tokens must be sent in the Authorization header.",
    "The bearer of this report is the assessment lead.",
    '0,"Bearer of bad news","skeleton key",token ring,"password: see policy",ok',
    "Enter your password: it must contain at least one digit.",
    "The password: field is optional for local runs.",
    "INFO the field api_key: is required",
    "Set api_key: in the configuration file, never in code.",
    "The API key: you get it from the provider's dashboard.",
    '{"password": null}',
    "password = 'see the onboarding guide for how to choose one'",
    "Authorization: Basic authentication is disabled in production.",
    "Authorization: token-based access is planned for Q3.",
    "INFO pwd=/home/runner/work",
    "INFO token=EOF reached",
    "https://example.com/path?key=id&token=page2",
    "ERROR KeyError: 'api_key'",
    "DEBUG token=None",
    '{"token": 50256}',
    "INFO access_token_ttl=3600",
    "INFO password_min_length=12",
]


@pytest.fixture(scope="module")
def copies():
    return {name: load(name, path) for name, path in FILES.items()}


def test_the_fixture_is_the_measured_corpus():
    assert {kind: len(lines) for kind, lines in CORPUS.items()} == {
        "csv": 212, "logs": 993, "json": 109, "prose": 30, "urls": 15}
    for line in UNCHANGED:
        assert line in LINES, line


def _changed(rule):
    return [line for line in LINES if rule(line)]


@pytest.mark.parametrize("name", ["backend", "eval"])
def test_the_text_rule_changes_fewer_than_one_line_in_a_hundred(copies, name):
    scrub = copies[name].scrub_text
    changed = _changed(lambda line: scrub(line) != line)
    assert len(changed) < LIMIT * len(LINES), (len(changed), [(line, scrub(line)) for line in changed[:20]])


@pytest.mark.parametrize("name", ["backend", "platform"])
def test_the_ledger_copy_masks_fewer_than_one_line_in_a_hundred(copies, name):
    module = copies[name]
    masked = _changed(lambda line: module.masked_for_ledger({"text": line}) != {"text": line})
    held = _changed(lambda line: module.holds_plaintext_secret({"text": line}))
    assert len(masked) < LIMIT * len(LINES), (len(masked), masked[:20])
    assert len(held) < LIMIT * len(LINES), (len(held), held[:20])


@pytest.mark.parametrize("name", ["backend", "eval"])
def test_the_lines_once_redacted_by_mistake_stay_as_they_are_in_text(copies, name):
    scrub = copies[name].scrub_text
    changed = [(line, scrub(line)) for line in UNCHANGED if scrub(line) != line]
    assert changed == []


@pytest.mark.parametrize("name", ["backend", "platform"])
def test_the_lines_once_redacted_by_mistake_stay_as_they_are_in_ledger_copies(copies, name):
    module = copies[name]
    for line in UNCHANGED:
        assert module.masked_for_ledger({"text": line}) == {"text": line}, line
        assert module.plaintext_secret_paths({"text": line}) == [], line


def test_a_stored_text_field_is_never_rewritten(copies):
    """A kept field keeps its text byte for byte; the stored rule only ever drops a field."""
    without = copies["backend"].without_stored_secrets
    rewritten, dropped = [], []
    for line in LINES:
        new, paths = without({"prompt": line})
        if new == {}:
            dropped.append(line)
        elif new != {"prompt": line}:
            rewritten.append((line, new))
    assert rewritten == []
    assert len(dropped) < LIMIT * len(LINES), dropped[:20]
