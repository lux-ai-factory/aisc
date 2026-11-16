"""The start page's Create project (homepage/index.html) says what the platform answered, in words.

An HTML 502 from Caddy while the platform restarts, or a refusal whose detail is a list of field errors, used to
come out as the JSON parser's text or '[object Object]'; and a second click while the first create was on its
way sent a second create. The page's script is run under node with a stub DOM, FormData and fetch."""
import json
import re
import shutil
import subprocess

import pytest

from conftest import ROOT

HARNESS = r"""
const vm = require('vm');
const [source, scenario] = [process.argv[2], JSON.parse(process.argv[3])];
process.on('unhandledRejection', () => {});
const els = {};
const el = (id) => els[id] || (els[id] = {id, innerHTML: '', textContent: '', disabled: false, listeners: {},
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); },
  fire(t) { (this.listeners[t] || []).forEach((fn) => fn({type: t, target: this, preventDefault() {}})); },
  showModal() {}, close() {}});
const posts = [];
function fetch(path, init) {
  if (!init || !init.method || init.method === 'GET') {
    return Promise.resolve({ok: true, status: 200, json: () => Promise.resolve([]), text: () => Promise.resolve('[]')});
  }
  posts.push(path);
  const a = scenario.create;
  if (a === 'pending') return new Promise(() => {});
  if (a === 'down') return Promise.reject(new TypeError('Failed to fetch'));
  const json = a.html ? () => Promise.reject(new SyntaxError("Unexpected token '<', \"<html><bod\"... is not valid JSON"))
                      : () => Promise.resolve(a.body);
  return Promise.resolve({ok: a.status < 400, status: a.status, json, text: () => Promise.resolve(a.html || JSON.stringify(a.body))});
}
class FormData { constructor() {} get(k) { return k === 'name' ? 'Pilot' : ''; } }
const ctx = {document: {getElementById: el, createElement: () => ({}), addEventListener() {}, querySelector: () => null},
             fetch, FormData, location: {href: '', pathname: '/', search: ''}, console, setTimeout,
             encodeURIComponent, decodeURIComponent, URLSearchParams, JSON};
ctx.window = ctx;   // a page's globals and window's are one, so a shared script's window.aisc is seen as aisc
const win = ctx;
vm.createContext(ctx);
vm.runInContext(source, ctx);
setTimeout(() => {
  for (let i = 0; i < (scenario.clicks || 1); i++) el('new-form').fire('submit');
  setTimeout(() => console.log(JSON.stringify({err: el('err').textContent, posts, href: win.location.href})), 80);
}, 30);
"""


def _page_script():
    """The page's own script, after the shared launcher script when the page loads it."""
    html = (ROOT / "homepage/index.html").read_text()
    own = next(s for s in re.findall(r"<script>(.*?)</script>", html, re.S) if "new-form" in s)
    shared = (ROOT / "homepage/assets/page.js").read_text() if 'src="/assets/page.js"' in html else ""
    return shared + "\n" + own


def _create(tmp_path, scenario):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    (tmp_path / "h.js").write_text(HARNESS)
    r = subprocess.run(["node", str(tmp_path / "h.js"), _page_script(), json.dumps(scenario)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout)


def test_an_html_answer_from_a_restarting_platform_is_not_shown_as_parser_text(tmp_path):
    out = _create(tmp_path, {"create": {"status": 502, "html": "<html><body>502 Bad Gateway</body></html>"}})
    assert "Unexpected token" not in out["err"] and "JSON" not in out["err"], f"the person reads {out['err']!r}"
    assert out["err"], "nothing is said"


def test_a_refusal_with_field_errors_names_the_field_problem(tmp_path):
    body = {"detail": [{"loc": ["body", "name"], "msg": "String should have at most 80 characters",
                        "type": "string_too_long"}]}
    out = _create(tmp_path, {"create": {"status": 422, "body": body}})
    assert "[object Object]" not in out["err"], f"the person reads {out['err']!r}"
    assert "at most 80 characters" in out["err"], out["err"]


def test_a_second_click_while_the_first_create_is_on_its_way_sends_nothing(tmp_path):
    out = _create(tmp_path, {"create": "pending", "clicks": 2})
    assert len(out["posts"]) == 1, f"two clicks sent {len(out['posts'])} creates"


def test_a_string_refusal_reads_as_the_platforms_words(tmp_path):
    out = _create(tmp_path, {"create": {"status": 409, "body": {"detail": "a project named Pilot exists"}}})
    assert out["err"] == "a project named Pilot exists"
