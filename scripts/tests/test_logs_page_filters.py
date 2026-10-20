"""homepage/logs.html sends only the filters a person filled in: the page builds the query from
the form and drops the empty fields, so an empty "from" or "actor" does not reach the platform as a filter.
`[].slice.call(submitted.keys())` was always [] (an iterator has no length), so nothing was dropped.

Runs the page's own two lines in node, with a stand-in form. Replaces the source greps of
test_stale_code.py (retired)."""
import json
import shutil
import subprocess

import pytest

from conftest import ROOT

HARNESS = r"""
const lines = process.argv[1];
const fields = JSON.parse(process.argv[2]);
const document = {getElementById: () => ({})};
function FormData() { return fields; }          // the form's fields as [name, value] pairs
let submitted = null;
eval(lines);
process.stdout.write(submitted.toString());
"""


def _filter_lines() -> str:
    lines = (ROOT / "homepage/logs.html").read_text().splitlines()
    i = next(n for n, line in enumerate(lines) if "submitted = new URLSearchParams(new FormData(" in line)
    return "\n".join(lines[i:i + 2])


def test_the_logs_page_sends_only_the_filters_filled_in():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    fields = [["actor", ""], ["action", "project.created"], ["from", ""], ["app", "platform"]]
    r = subprocess.run(["node", "-e", HARNESS, _filter_lines(), json.dumps(fields)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "action=project.created&app=platform"
