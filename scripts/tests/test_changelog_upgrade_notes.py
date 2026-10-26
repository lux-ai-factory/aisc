"""The CHANGELOG's Unreleased section tells an operator what an upgrade of an existing install needs, first,
before the list of changes: the identifiers an operator acts on are named (secrets, commands, migrations,
variables, versions), and the text holds no em dash.

Run from the repo root:

    uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_changelog_upgrade_notes.py
"""

import re

import pytest

from conftest import ROOT

HEADING = "### Upgrading an existing install"
NAMED = (
    "PLATFORM_ENGINE_TOKEN", "scripts/aisc.py secrets", "0.4.0", "0013_run_pass_use",
    "0014_ledger_content_redaction", "0022_run_key_pass", "0023_connection_secret_headers",
    "0024_connection_capabilities", "0024_drop_stored_langbite_judge_keys", "scripts/clean-old-secrets.sh",
    "docs/runbooks/clean-old-secrets.md", "--apply", "retired", "AISC_TARGET_API_KEY", "OPENAI_API_KEY",
    "0.3.0+aisc.1", "promptfoo",
)


def _unreleased() -> str:
    text = (ROOT / "CHANGELOG.md").read_text()
    start = re.search(r"^## Unreleased\b.*$", text, re.M)
    assert start, "CHANGELOG.md has no '## Unreleased' section"
    rest = text[start.end():]
    following = re.search(r"^## ", rest, re.M)
    return rest[:following.start()] if following else rest


def test_the_upgrade_notes_come_first_before_the_changes():
    section = _unreleased()
    assert HEADING in section
    assert "### Changes" in section
    assert section.index(HEADING) < section.index("### Changes")


@pytest.mark.parametrize("name", NAMED)
def test_the_section_names_what_an_operator_acts_on(name):
    assert name in _unreleased()


def test_the_section_holds_no_em_dash():
    assert "—" not in _unreleased()
