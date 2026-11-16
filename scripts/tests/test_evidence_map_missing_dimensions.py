"""The Evidence map (homepage/evidence-map.html) says why a test with no dimensions cannot be linked.

A local test (the Mijke tests, for example) has no dimensions until an admin ticks them on its catalogue entry.
Until then every objective with a dimension refuses it, and the map used to show a bare dot with no reason.
The page's script is run under node on a stub DOM with the platform's evidence answer."""
import json
import shutil
import subprocess

import pytest

from conftest import ROOT

PAGE = ROOT / "homepage/evidence-map.html"

HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const [file, scenario] = process.argv.slice(2);
const html = fs.readFileSync(file, 'utf8'), s = JSON.parse(scenario);
class Node {}
class El extends Node {
  constructor(tag) { super(); this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {}; this.className = '';
                     this.hidden = false; this.value = ''; this.checked = false; this.type = ''; this._text = '';
                     this.title = ''; this.listeners = {}; this.style = {}; this.disabled = false; }
  appendChild(c) { this.children.push(c); c.parentNode = this; return c; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  set textContent(t) { this._text = String(t); this.children = []; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  all() { return this.children.flatMap((c) => c instanceof El ? [c, ...c.all()] : []); }
  querySelectorAll(sel) { return this.all().filter((c) => c.tagName === sel.toUpperCase()); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  scrollIntoView() {}
  // what a person can read in this element: its text, and the tooltips and labels of everything in it
  said() { return [this.textContent, ...[this, ...this.all()].flatMap((c) => [c.title, c.getAttribute('aria-label') || ''])]
                  .filter(Boolean).join(' '); }
}
class Text extends Node { constructor(t) { super(); this.textContent = String(t); } }
const byId = {};
for (const m of html.replace(/<script[\s\S]*?<\/script>/gi, '').matchAll(/<(\w+)\b([^>]*)>/g)) {
  const id = /\bid="([^"]+)"/.exec(m[2]);
  if (id) byId[id[1]] = new El(m[1]);
}
const document = {getElementById: (id) => byId[id] || null, createElement: (t) => new El(t),
                  createTextNode: (t) => new Text(t), title: ''};
function fetch(path) {
  let body = {};
  if (path === '/api/projects/demo') body = {name: 'Demo'};
  else if (path.startsWith('/api/projects/demo/evidence')) body = s.evidence;
  else if (path.startsWith('/oauth2/')) body = {user: 'alice'};
  return Promise.resolve({ok: true, status: 200, json: () => Promise.resolve(body),
                          text: () => Promise.resolve(JSON.stringify(body))});
}
const ctx = {document, fetch, Node, URLSearchParams, encodeURIComponent, JSON, console, Date,
             location: {search: '?project=demo', replace() {}}};
ctx.window = ctx;   // a page's globals and window's are one
vm.createContext(ctx);
for (const m of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
  // the shared page.js, as the browser loads it (window's globals are the page's: aisc is window.aisc)
  if (/\bsrc="\/assets\/page\.js"/.test(m[1])) {
    vm.runInContext(fs.readFileSync(require('path').join(require('path').dirname(file), 'assets/page.js'), 'utf8'), ctx);
    ctx.aisc = ctx.window.aisc;
  } else vm.runInContext(m[2], ctx);
}
setTimeout(() => {
  const [thead, tbody] = byId['grid'].children;
  const heads = thead.children[0].children, cells = tbody.children[0].children;
  const column = (label) => heads.findIndex((th) => th.textContent.includes(label));
  const read = (label) => { const i = column(label); return {head: heads[i].said(), cell: cells[i].said(),
                                                             button: cells[i].querySelectorAll('button').length}; };
  console.log(JSON.stringify({local: read('Mijke tests'), tagged: read('LangBiTe')}));
}, 80);
"""

EVIDENCE = {
    "versions": [{"pid": "v2", "number": 2}], "version": {"pid": "v2", "number": 2},
    "can_edit": True, "can_review": False, "read_only": False, "carried_from": None, "review": None,
    "objectives": [{"id": "O1", "title": "Fair treatment of every group", "dimension": "REQ6", "risks": [],
                    "linked": False, "evidence": "not covered", "expects": "Test", "priority": False, "stale": None}],
    "tests": [{"key": "mijke-tests", "label": "Mijke tests", "dimensions": [], "stale": None},
              {"key": "aisc-plugin-langbite", "label": "LangBiTe", "dimensions": ["REQ6"], "stale": None}],
    "controls": [], "links": [], "coverage": {"objectives": 1, "linked": 0, "gaps": 1},
}


def run_map(tmp_path):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    (tmp_path / "h.js").write_text(HARNESS)
    r = subprocess.run(["node", str(tmp_path / "h.js"), str(PAGE), json.dumps({"evidence": EVIDENCE})],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout)


def test_a_test_with_no_dimensions_says_why_it_cannot_be_linked(tmp_path):
    local = run_map(tmp_path)["local"]
    said = (local["head"] + " " + local["cell"]).lower()
    assert "dimension" in said, f"the Mijke tests column gives no reason it cannot be linked: {local}"


def test_a_test_in_the_objectives_dimension_is_offered_as_a_link(tmp_path):
    assert run_map(tmp_path)["tagged"]["button"] == 1
