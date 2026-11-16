"""How to report a vulnerability (SECURITY.md) and what to do in an incident (docs/runbooks/incident.md): each has
its sections, the runbook names only commands that exist, and the security appendix links to both.

Read-only: the documents as text.
"""

import re

from conftest import ROOT

SECURITY = ROOT / "SECURITY.md"
INCIDENT = ROOT / "docs/runbooks/incident.md"


def test_the_reporting_route_has_its_sections():
    assert SECURITY.is_file(), "no SECURITY.md: nobody knows where to report a vulnerability"
    text = SECURITY.read_text()
    missing = [h for h in ("## Reporting a vulnerability", "## What to expect", "## Scope", "## Supported versions")
               if h not in text]
    assert missing == []


def test_the_incident_runbook_has_its_sections():
    assert INCIDENT.is_file(), "no incident runbook"
    text = INCIDENT.read_text()
    missing = [h for h in ("## Who decides", "## Contain", "## Rotate", "## Restore", "## Notify",
                           "## Record in the ledger") if h not in text]
    assert missing == []


def test_every_command_the_runbook_names_exists():
    assert INCIDENT.is_file(), "no incident runbook"
    text = INCIDENT.read_text()
    named = set(re.findall(r"scripts/[\w./-]+\.(?:sh|py)", text)) | set(re.findall(r"docs/runbooks/[\w.-]+\.md", text))
    assert sorted(p for p in named if not (ROOT / p).is_file()) == []


def test_the_security_appendix_links_to_both():
    text = (ROOT / "docs/appendices/security.md").read_text()
    assert "SECURITY.md" in text and "runbooks/incident.md" in text


def test_no_em_dash_in_the_new_docs():
    for f in (SECURITY, INCIDENT):
        assert f.is_file(), f"{f.name} is missing"
        assert "\u2014" not in f.read_text(), f.name
