"""In the AI Assessment Sandbox, Run tests and Results open only once a part of the AI system is connected.

homepage/assets/sandbox-gate.js decides from the platform's targets answer (GET /api/projects/{slug}/targets): the
two are open when the system or one of its card components has an endpoint or an uploaded file; otherwise they are
greyed out and name the system to connect. A targets call that failed never locks them. Answer checklists and Report
never wait, and the project page's sandbox card always opens. The function is run here in node, as the browser
would; the pages' use of it is checked in their source.
"""
import json
import re
import shutil
import subprocess

import pytest

from conftest import ROOT

GATE_JS = ROOT / "homepage/assets/sandbox-gate.js"
PROJECT = ROOT / "homepage/project.html"
SANDBOX = ROOT / "homepage/evidence.html"

_HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const [file, scenario] = process.argv.slice(1);
const s = JSON.parse(scenario);
const window = {};
vm.runInNewContext(fs.readFileSync(file, 'utf8'), {window});
process.stdout.write(JSON.stringify(window.aiscSandboxGate(s.answer, s.project)));
"""


def gate(answer, project="Noa demo"):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", _HARNESS, str(GATE_JS), json.dumps({"answer": answer, "project": project})],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def target(kind, label, endpoint=None, file=None):
    return {"key": "system" if kind == "system" else "component:" + label, "kind": kind, "label": label,
            "endpoint": endpoint, "file": file}


NOTHING = {"ok": True, "status": 200, "data": {"targets": [
    target("system", "Noa"), target("component", "OpenAI model"), target("component", "Organisation list")]}}


def test_nothing_connected_closes_the_card_and_names_the_system():
    assert gate(NOTHING) == {"open": False, "system": "Noa"}


def test_one_component_with_an_endpoint_opens_the_card():
    answer = json.loads(json.dumps(NOTHING))
    answer["data"]["targets"][1]["endpoint"] = {"kind": "mijke", "base_url": "http://10.52.28.7:8080"}
    assert gate(answer) == {"open": True}


def test_an_uploaded_file_counts_as_connected():
    answer = json.loads(json.dumps(NOTHING))
    answer["data"]["targets"][2]["file"] = {"name": "organisations.csv", "size": 10}
    assert gate(answer) == {"open": True}


def test_the_system_itself_connected_opens_the_card():
    answer = json.loads(json.dumps(NOTHING))
    answer["data"]["targets"][0]["endpoint"] = {"kind": "openai"}
    assert gate(answer) == {"open": True}


@pytest.mark.parametrize("answer", [
    {"ok": False, "status": 0, "data": None},
    {"ok": False, "status": 403, "data": {"detail": "no"}},
    {"ok": True, "status": 200, "data": {}},
])
def test_an_answer_that_says_nothing_never_locks_the_card(answer):
    assert gate(answer) == {"open": True}


def test_without_a_system_target_the_project_name_is_used():
    answer = {"ok": True, "status": 200, "data": {"targets": [target("component", "OpenAI model")]}}
    assert gate(answer, "Noa demo") == {"open": False, "system": "Noa demo"}


def scripts_of(html):
    return "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S | re.I))


def test_the_sandbox_page_gates_run_tests_and_results_only():
    html = SANDBOX.read_text()
    assert '<script src="/assets/sandbox-gate.js"></script>' in html
    script = scripts_of(html)
    assert "/targets" in script and "aiscSandboxGate(" in script
    assert re.search(r'<p class="wait" id="tests-wait" hidden></p>', html), "the sentence under Run tests"
    assert re.search(r'<p class="wait" id="results-wait" hidden></p>', html), "the sentence under Results"
    assert "['execute-tests', 'tests-wait']" in script and "['visualise', 'results-wait']" in script
    assert "address-controls" not in re.search(r"function gateWays.*?\n  }\n", script, re.S).group(0)
    assert "write-report" not in re.search(r"function gateWays.*?\n  }\n", script, re.S).group(0)
    assert "Connect at least one component of " in script
    assert "'/connectivity.html?project=' + enc(slug)" in script
    assert "Ask an owner of the project to connect one." in script
    assert "visibilitychange" in script, "checked again when the person comes back to the tab"


def test_the_project_page_sandbox_card_always_opens():
    html = PROJECT.read_text()
    assert "sandbox-gate.js" not in html and "sandbox-wait" not in html and "aiscSandboxGate" not in html
    assert "document.getElementById('sandbox-card').href = '/evidence.html?project='" in html
