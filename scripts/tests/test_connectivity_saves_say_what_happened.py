"""Manage > Connectivity (homepage/connectivity.html): every save says what happened.

Saving an agent, a connection's test tool roles or a new provider connection says so when the platform does
not answer, gives the platform's own words for a refusal whose detail is a list of field errors (FastAPI's 422),
and shows that a save is under way while it is. The page's own script is run in node on stub answers."""
import json
import shutil
import subprocess

import pytest

from conftest import ROOT

PAGE = ROOT / "homepage/connectivity.html"

# A stand-in DOM: one element per id in the markup and the elements the script makes. Reads answer as the
# platform would; writes answer as the scenario says: "down" (nothing answers), "pending" (no answer yet) or
# {"status", "body"}.
_HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const [file, scenario] = process.argv.slice(2);
const html = fs.readFileSync(file, 'utf8'), s = JSON.parse(scenario);
const unhandled = [];
process.on('unhandledRejection', (e) => unhandled.push(String(e)));
class Node {}
class El extends Node {
  constructor(tag) { super(); this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {}; this.className = '';
                     this.hidden = false; this.value = ''; this.checked = false; this.type = ''; this._text = '';
                     this.listeners = {}; this.style = {}; this.disabled = false; }
  appendChild(c) { this.children.push(c); c.parentNode = this; return c; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  set textContent(t) { this._text = String(t); this.children = []; }
  get options() { return this.children.filter((c) => c.tagName === 'OPTION'); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  fire(type) { (this.listeners[type] || []).forEach((fn) => fn({type, target: this, preventDefault() {}})); }
  all() { return this.children.flatMap((c) => c instanceof El ? [c, ...c.all()] : []); }
  querySelectorAll(sel) {
    return this.all().filter((c) => sel[0] === '.' ? c.className.split(' ').includes(sel.slice(1))
                                                   : c.tagName === sel.toUpperCase());
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  closest() { return null; }
}
class Text extends Node { constructor(t) { super(); this.textContent = String(t); } }
const byId = {}, root = new El('body');
for (const m of html.replace(/<script[\s\S]*?<\/script>/gi, '').matchAll(/<(\w+)\b([^>]*)>/g)) {
  const node = new El(m[1]), id = /\bid="([^"]+)"/.exec(m[2]), cls = /\bclass="([^"]+)"/.exec(m[2]);
  const tab = /\bdata-tab="([^"]+)"/.exec(m[2]);
  if (cls) node.className = cls[1];
  if (tab) node.setAttribute('data-tab', tab[1]);
  if (id) byId[id[1]] = node;
  if (id || tab) root.appendChild(node);
}
const document = {getElementById: (id) => byId[id] || null, createElement: (t) => new El(t),
                  createTextNode: (t) => new Text(t), querySelectorAll: (sel) => root.querySelectorAll(sel),
                  querySelector: (sel) => root.querySelectorAll(sel)[0] || null, title: '',
                  addEventListener() {}};
const requests = [];
function answer(status, body) {
  return Promise.resolve({ok: status < 400, status, json: () => Promise.resolve(body),
                          text: () => Promise.resolve(JSON.stringify(body))});
}
function fetch(path, init) {
  const method = (init && init.method) || 'GET';
  requests.push({method, path});
  if (method !== 'GET') {
    if (s.write === 'down') return Promise.reject(new TypeError('Failed to fetch'));
    if (s.write === 'pending') return new Promise(() => {});
    return answer(s.write.status, s.write.body);
  }
  if (path === '/api/projects/demo') return answer(200, {name: 'Demo'});
  if (path === '/api/projects/demo/connectivity') return answer(200, s.connectivity);
  if (path.endsWith('/models')) return answer(200, {models: [], error: 'not asked here'});
  return answer(200, {});
}
function confirm() { return true; }
const win = {addEventListener() {}, confirm};
const ctx = {document, fetch, Node, URLSearchParams, encodeURIComponent, JSON, console, confirm,
             location: {search: '?project=demo', pathname: '/connectivity.html', hash: '', replace() {}}, setTimeout,
             history: {replaceState() {}}, window: win};
ctx.addEventListener = win.addEventListener; ctx.window = ctx;   // window's globals are the page's: a shared script's window.aisc is aisc
vm.createContext(ctx);
const path = require('path');
for (const m of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
  const src = /\bsrc="\/(assets\/[^"]+)"/.exec(m[1]);
  vm.runInContext(src ? fs.readFileSync(path.join(path.dirname(file), src[1]), 'utf8') : m[2], ctx);
}
const wait = () => new Promise((r) => setTimeout(r, 60));
const conn = (name) => byId['connections'].children.find((tr) => tr.textContent.includes('(' + name + ')'));
(async () => {
  await wait();
  let button = null;
  if (s.action === 'agent') {
    const row = byId['agents'].children[0];
    row.querySelectorAll('select')[0].value = 'openai'; row.querySelectorAll('input')[0].value = 'gpt-4o';
    button = row.querySelectorAll('button').find((b) => b.textContent === 'Save');
    button.fire('click');
  } else if (s.action === 'tool') {
    const box = conn('mistral').querySelectorAll('input').find((i) => i.value === 'judge');
    box.checked = true; box.fire('click'); box.fire('change');
    button = conn('mistral').querySelectorAll('button').find((b) => b.textContent === 'Save roles');
    button.fire('click');
  } else if (s.action === 'provider') {
    byId['n-name'].value = 'groq'; byId['n-label'].value = 'Groq'; byId['n-provider'].value = 'openai';
    byId['new-provider'].fire('submit');
  }
  await wait();
  const msg = {agents: byId['agents-msg'].textContent, connections: byId['connections-msg'].textContent,
               provider: byId['n-msg'].textContent};
  console.log(JSON.stringify({msg, unhandled, writes: requests.filter((r) => r.method !== 'GET'),
                              button: button ? {disabled: button.disabled, text: button.textContent} : null}));
})();
"""

CONNECTIVITY = {
    "components": [], "agents": [{"id": "card", "label": "Card agent", "choice": None}],
    "tools": [{"role": "judge", "connections": []}],
    "connections": [{"name": "openai", "label": "OpenAI", "kind": "provider", "protocol": "Provider",
                     "provider": "openai", "base_url": None, "has_secret": True, "secret_headers": [],
                     "target": None, "used_for": []},
                    {"name": "mistral", "label": "Mistral", "kind": "provider", "protocol": "Provider",
                     "provider": "mistral", "base_url": None, "has_secret": True, "secret_headers": [],
                     "target": None, "used_for": []}],
    "roles": ["judge", "attacker"],
    "providers": [{"id": "openai", "label": "OpenAI", "key_required": True, "base_url_editable": False}],
    "can_manage": True}

FIELD_ERRORS = {"detail": [{"loc": ["body", "label"], "msg": "String should have at most 120 characters",
                            "type": "string_too_long"}]}
WHERE = {"agent": "agents", "tool": "connections", "provider": "provider"}


def run_page(tmp_path, action, write):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    harness = tmp_path / "harness.js"
    harness.write_text(_HARNESS)
    scenario = {"connectivity": CONNECTIVITY, "action": action, "write": write}
    r = subprocess.run(["node", str(harness), str(PAGE), json.dumps(scenario)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    out = json.loads(r.stdout)
    assert out["writes"], f"the {action} save sent nothing: the harness did not reach it"
    return out


@pytest.mark.parametrize("action", ["agent", "tool", "provider"])
def test_a_save_the_platform_does_not_answer_says_so(tmp_path, action):
    out = run_page(tmp_path, action, "down")
    shown = out["msg"][WHERE[action]]
    assert "not answering" in shown, f"the {action} save shows {shown!r} when nothing answers"


@pytest.mark.parametrize("action", ["agent", "tool", "provider"])
def test_a_refusal_with_field_errors_says_which_field_and_why(tmp_path, action):
    out = run_page(tmp_path, action, {"status": 422, "body": FIELD_ERRORS})
    shown = out["msg"][WHERE[action]]
    assert "at most 120 characters" in shown, f"the {action} refusal reads {shown!r}"


@pytest.mark.parametrize("action", ["agent", "tool"])
def test_a_save_under_way_shows_it_and_cannot_be_sent_twice(tmp_path, action):
    out = run_page(tmp_path, action, "pending")
    shown = out["msg"][WHERE[action]]
    assert out["button"]["disabled"] or "Saving" in shown, \
        f"nothing shows the {action} save is under way: button {out['button']}, message {shown!r}"


def test_a_string_refusal_still_reads_as_the_platforms_words(tmp_path):
    out = run_page(tmp_path, "provider", {"status": 409, "body": {"detail": "a connection named groq exists"}})
    assert out["msg"]["provider"] == "a connection named groq exists"
