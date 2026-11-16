"""A weekly workflow audits every lock and scans every image the stack builds, and fails on high severity. Every
action it uses is pinned by commit. Scheduled workflows run only from the default branch, so it runs on schedule
once it is merged there.

Read-only: the workflow file as text.
"""

import re

import yaml

from conftest import ROOT

WEEKLY = ROOT / ".github/workflows/weekly-scan.yml"


def test_a_weekly_scan_fails_on_high_severity():
    assert WEEKLY.is_file(), "no weekly scan of the locks and the images"
    wf = yaml.safe_load(WEEKLY.read_text())
    on = wf[True] if True in wf else wf["on"]
    assert on["schedule"] == [{"cron": "0 5 * * 1"}] and "workflow_dispatch" in on
    steps = [s for j in wf["jobs"].values() for s in j["steps"]]
    grype = [s for s in steps if "anchore/scan-action" in (s.get("uses") or "")]
    assert grype, "the images are not scanned"
    assert all(s["with"]["fail-build"] is True and s["with"]["severity-cutoff"] == "high" for s in grype)
    assert all(re.search(r"@[0-9a-f]{40}$", s["uses"]) for s in steps if s.get("uses"))
    assert any("scripts/audit-dependencies.sh" in (s.get("run") or "") for s in steps)
