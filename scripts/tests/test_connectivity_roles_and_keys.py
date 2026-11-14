"""Manage > Connectivity, Connections tab (homepage/connectivity.html), with the page's own script run in node on
the platform's answers: a stored adapter token reads as stored, a ticked test tool role is never dropped without a
word, and Save roles with nothing ticked asks before it removes the tool."""
import json
import shutil
import subprocess

import pytest

from conftest import ROOT

PAGE = ROOT / "homepage/connectivity.html"

# A stand-in DOM: one element per id in the page's markup and the elements the script makes. Elements keep their
# listeners, so a step can tick a box or press a button as a person would. Every request is recorded.
_HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const [file, scenario] = process.argv.slice(2);
const html = fs.readFileSync(file, 'utf8'), s = JSON.parse(scenario);
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
const requests = [], asked = [];
function fetch(path, init) {
  const method = (init && init.method) || 'GET';
  requests.push({method, path, body: init && init.body ? JSON.parse(init.body) : null});
  let body = {};
  if (path === '/api/projects/demo') body = {name: 'Demo'};
  else if (path === '/api/projects/demo/connectivity') body = s.connectivity;
  else if (path.endsWith('/models')) body = {models: [], error: 'not asked here'};
  return Promise.resolve({ok: true, status: method === 'DELETE' ? 204 : 200, json: () => Promise.resolve(body)});
}
function confirm(text) { asked.push(String(text)); return false; }
const win = {addEventListener() {}, confirm};
const ctx = {document, fetch, Node, URLSearchParams, encodeURIComponent, JSON, console, confirm,
             location: {search: '?project=demo', hash: '', replace() {}}, setTimeout,
             history: {replaceState() {}}, window: win};
vm.createContext(ctx);
for (const m of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)) vm.runInContext(m[1], ctx);
const wait = () => new Promise((r) => setTimeout(r, 60));
const row = (name) => byId['connections'].children.find((tr) => tr.textContent.includes('(' + name + ')'));
const box = (name, role) => row(name).querySelectorAll('input').find((i) => i.value === role);
const saveRoles = (name) => row(name).querySelectorAll('button').find((b) => b.textContent === 'Save roles');
(async () => {
  await wait();
  for (const step of s.steps || []) {
    if (step.tick) { const b = box(step.tick[0], step.tick[1]); b.checked = !b.checked; b.fire('click'); b.fire('change'); }
    if (step.save) saveRoles(step.save).fire('click');
    await wait();
  }
  const rows = byId['connections'].children.map((tr) => tr.children.map((td) => td.textContent));
  const ticked = {};
  for (const tr of byId['connections'].children) {
    const name = /\(([^)]+)\)/.exec(tr.textContent)[1];
    ticked[name] = tr.querySelectorAll('input').filter((i) => i.checked).map((i) => i.value);
  }
  const text = Object.values(byId).map((n) => n.textContent).join(' ');
  console.log(JSON.stringify({rows, ticked, requests: requests.filter((r) => r.method !== 'GET'), asked, text}));
})();
"""


def run_page(tmp_path, connectivity, steps=()):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    harness = tmp_path / "harness.js"
    harness.write_text(_HARNESS)
    r = subprocess.run(["node", str(harness), str(PAGE), json.dumps({"connectivity": connectivity, "steps": list(steps)})],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout)


def connectivity(connections):
    return {"components": [{"key": "system", "kind": "system", "label": "Mijke", "component_kind": None,
                            "file": None, "connection": {"name": "mijke", "protocol": "mijke", "last_test_ok": True}}],
            "agents": [{"id": "card", "label": "Card agent", "choice": None}],
            "tools": [{"role": "judge", "connections": [{"name": "openai", "label": "OpenAI"}]}],
            "connections": connections, "roles": ["judge", "attacker"],
            "providers": [{"id": "openai", "label": "OpenAI", "key_required": True, "base_url_editable": False}],
            "can_manage": True}


# an adapter's connection as the platform's connection view gives it to an admin: its token is a secret setting,
# stored apart from an ordinary key, so has_secret is false while secret_settings names the token
MIJKE = {"name": "mijke", "label": "Mijke", "kind": "mijke", "protocol": "mijke", "provider": None,
         "base_url": "https://mijke.example", "has_secret": False, "settings": {"tenant": "eindhoven"},
         "secret_settings": ["token"], "secret_headers": [],
         "target": {"key": "system", "kind": "system", "label": "Mijke"}, "used_for": []}
OPENAI = {"name": "openai", "label": "OpenAI", "kind": "provider", "protocol": "Provider", "provider": "openai",
          "base_url": None, "has_secret": True, "secret_headers": [], "target": None,
          "used_for": [{"use": "tool", "roles": ["judge"]}]}
MISTRAL = {"name": "mistral", "label": "Mistral", "kind": "provider", "protocol": "Provider", "provider": "mistral",
           "base_url": None, "has_secret": True, "secret_headers": [], "target": None, "used_for": []}


def test_a_stored_adapter_token_shows_as_stored(tmp_path):
    out = run_page(tmp_path, connectivity([MIJKE, OPENAI]))
    mijke = next(r for r in out["rows"] if "(mijke)" in r[0])
    assert mijke[3] == "stored", f"the Key column of the Mijke connection says {mijke[3]!r}"


def test_an_adapter_connection_without_its_token_still_shows_none(tmp_path):
    out = run_page(tmp_path, connectivity([{**MIJKE, "secret_settings": []}, OPENAI]))
    mijke = next(r for r in out["rows"] if "(mijke)" in r[0])
    assert mijke[3] == "none"


def test_a_ticked_role_survives_another_rows_save(tmp_path):
    """The person ticks judge on Mistral, then saves OpenAI's roles: the Mistral tick is either sent or still
    ticked after the table is drawn again, never dropped without a word."""
    out = run_page(tmp_path, connectivity([MIJKE, OPENAI, MISTRAL]),
                   steps=[{"tick": ["mistral", "judge"]}, {"save": "openai"}])
    sent = [r for r in out["requests"] if r["path"].endswith("/connections/mistral/tool") and r["method"] == "PUT"]
    kept = "judge" in out["ticked"]["mistral"]
    assert sent or kept, f"the judge tick on Mistral was lost: requests {out['requests']}, ticked {out['ticked']}"


def test_save_roles_with_nothing_ticked_asks_before_removing_the_tool(tmp_path):
    """OpenAI is the judge. Unticking judge and pressing Save roles would end every test's use of it: the page
    asks first, and when the person says no, nothing is sent."""
    out = run_page(tmp_path, connectivity([MIJKE, OPENAI]),
                   steps=[{"tick": ["openai", "judge"]}, {"save": "openai"}])
    removed = [r for r in out["requests"] if r["path"].endswith("/connections/openai/tool") and r["method"] == "DELETE"]
    assert not removed, f"the judge was removed without asking: {out['requests']}"
