"""What every launcher page needs from the platform, in one script: homepage/assets/page.js.

aisc.project() is the project the page is about, from ?project=<slug> or /p/<slug>, or null: an address
that is not a project handle, a malformed escape included, never stops the page. aisc.call(path, {method,
body}) calls the platform with the person's sign-in and always settles on {ok, status, data, message}:
the platform's own words when it refused (FastAPI's detail, a sentence or a list of field errors), a plain
'Refused (HTTP n)' when it gave none or the answer was not JSON (Caddy's 502 while the platform is down),
and status 0 when nothing answered. The script is run here in node, as the browser would.
"""
import json
import shutil
import subprocess

import pytest

from conftest import ROOT

PAGE_JS = ROOT / "homepage/assets/page.js"

_HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const [file, scenario] = process.argv.slice(2);
const s = JSON.parse(scenario);
const sent = [];
function fetch(path, init) {
  sent.push({path, init});
  if (s.answer === 'down') return Promise.reject(new TypeError('Failed to fetch'));
  const a = s.answer || {};
  return Promise.resolve({ok: a.status >= 200 && a.status < 300, status: a.status,
                          text: () => Promise.resolve(a.body === undefined ? '' : a.body)});
}
const window = {};
const ctx = {window, fetch, URLSearchParams, decodeURIComponent, JSON,
             location: {pathname: s.pathname || '/x.html', search: s.search || ''}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(file, 'utf8'), ctx);
const out = {project: window.aisc.project()};
if (!s.call) { console.log(JSON.stringify(out)); }
else window.aisc.call(s.call.path, s.call.opts).then((answer) => {
  out.answer = answer; out.sent = sent; console.log(JSON.stringify(out));
});
"""


def run(tmp_path, **scenario):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    assert PAGE_JS.is_file(), "missing feature: homepage/assets/page.js"
    harness = tmp_path / "harness.js"
    harness.write_text(_HARNESS)
    r = subprocess.run(["node", str(harness), str(PAGE_JS), json.dumps(scenario)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout)


@pytest.mark.parametrize("where, want", [
    ({"search": "?project=demo-2"}, "demo-2"),
    ({"pathname": "/p/demo-2"}, "demo-2"),
    ({"pathname": "/p/demo-2/", "search": "?open=catalogue"}, "demo-2"),
    ({"pathname": "/p/%64emo"}, "demo"),
    ({"pathname": "/p/%E0%A4%A"}, None),                  # a malformed escape: no project, no throw
    ({"search": "?project=Not%20a%20handle"}, None),
    ({"search": "?project=" + "a" * 65}, None),
    ({"search": "?project="}, None),
    ({"pathname": "/p/"}, None),
    ({}, None),
])
def test_the_project_is_the_handle_in_the_address_or_none(tmp_path, where, want):
    assert run(tmp_path, **where)["project"] == want


def call(tmp_path, answer, path="/api/projects/demo", opts=None):
    return run(tmp_path, answer=answer, call={"path": path, "opts": opts})


def test_an_answer_is_its_json(tmp_path):
    out = call(tmp_path, {"status": 200, "body": json.dumps({"name": "Demo"})})
    assert out["answer"] == {"ok": True, "status": 200, "data": {"name": "Demo"}, "message": None}
    assert out["sent"] == [{"path": "/api/projects/demo",
                            "init": {"method": "GET", "credentials": "same-origin", "headers": {}}}]


def test_a_body_is_sent_as_json_with_the_sign_in(tmp_path):
    out = call(tmp_path, {"status": 201, "body": "{}"}, path="/api/projects",
               opts={"method": "POST", "body": {"name": "Demo"}})
    assert out["sent"][0]["init"] == {"method": "POST", "credentials": "same-origin",
                                      "headers": {"Content-Type": "application/json"},
                                      "body": json.dumps({"name": "Demo"}, separators=(",", ":"))}


def test_an_empty_answer_is_no_data(tmp_path):
    assert call(tmp_path, {"status": 204})["answer"] == {"ok": True, "status": 204, "data": None, "message": None}


def test_a_refusal_is_in_the_platforms_words(tmp_path):
    out = call(tmp_path, {"status": 404, "body": json.dumps({"detail": "no project 'demo'"})})
    assert out["answer"] == {"ok": False, "status": 404, "data": {"detail": "no project 'demo'"},
                             "message": "no project 'demo'"}


def test_field_errors_are_listed(tmp_path):
    detail = [{"loc": ["body", "name"], "msg": "Field required", "type": "missing"},
              {"loc": ["body", "slug"], "msg": "String should match pattern", "type": "string_pattern_mismatch"}]
    out = call(tmp_path, {"status": 422, "body": json.dumps({"detail": detail})})
    assert out["answer"]["message"] == "Field required; String should match pattern"


def test_a_refusal_without_words_says_its_status(tmp_path):
    out = call(tmp_path, {"status": 403, "body": json.dumps({"error": "forbidden"})})
    assert out["answer"]["message"] == "Refused (HTTP 403)"


def test_an_answer_that_is_not_json_is_no_data_and_no_error_page(tmp_path):
    out = call(tmp_path, {"status": 502, "body": "<html>Bad Gateway</html>"})
    assert out["answer"] == {"ok": False, "status": 502, "data": None, "message": "Refused (HTTP 502)"}


def test_nothing_answering_is_status_0_and_never_a_rejection(tmp_path):
    out = call(tmp_path, "down")
    assert out["answer"] == {"ok": False, "status": 0, "data": None, "message": "The platform is not answering."}
