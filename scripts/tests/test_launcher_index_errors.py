"""The launcher's list of projects says when the platform refused to list them.

A 500, 403 or 503 from /api/projects rendered "No projects yet. Create one to begin an assessment.", so a
person created a project that already existed. The list script of homepage/index.html is run under node
with a stub DOM and fetch."""
import json
import re
import shutil
import subprocess

import pytest

from conftest import ROOT

HARNESS = r"""
const vm = require('vm');
const [source, answer] = [process.argv[2], JSON.parse(process.argv[3])];
const els = {};
const el = (id) => els[id] || (els[id] = {id, innerHTML: '', textContent: '', addEventListener() {}, showModal() {}});
const fetch = () => answer === null ? Promise.reject(new TypeError('Failed to fetch'))
  : Promise.resolve({ok: answer.status < 400, status: answer.status, json: () => Promise.resolve(answer.body)});
const ctx = {document: {getElementById: el, createElement: () => ({})}, fetch, window: {location: {}}, console};
vm.createContext(ctx);
vm.runInContext(source, ctx);
setTimeout(() => console.log(JSON.stringify(el('projects').innerHTML)), 50);
"""


def _list_script():
    html = (ROOT / "homepage/index.html").read_text()
    return next(s for s in re.findall(r"<script>(.*?)</script>", html, re.S) if "var list = " in s)


def _rendered(tmp_path, answer):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    (tmp_path / "h.js").write_text(HARNESS)
    r = subprocess.run(["node", str(tmp_path / "h.js"), _list_script(), json.dumps(answer)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout)


@pytest.mark.parametrize("status", [500, 403, 503])
def test_a_refused_list_says_so_and_does_not_read_no_projects_yet(tmp_path, status):
    shown = _rendered(tmp_path, {"status": status, "body": {"detail": "boom"}})
    assert "No projects yet" not in shown, shown
    assert str(status) in shown and "could not be listed" in shown, shown


def test_an_empty_list_still_reads_no_projects_yet(tmp_path):
    assert "No projects yet" in _rendered(tmp_path, {"status": 200, "body": []})


def test_no_answer_still_reads_could_not_reach(tmp_path):
    assert "Could not reach the platform service." in _rendered(tmp_path, None)
