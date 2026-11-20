"""The sandbox page (homepage/evidence.html) says that a test's dashboard tile was deleted, and offers to make it again.

Opening the tile of a test whose tile someone deleted in the results dashboard sends the person here with
?tile_deleted=<package>::<name> (the platform's dashboards/open). The page names the test, says why there is
nothing to open, and gives an editor a button that asks the platform to make the tile again, then opens it; a viewer
is told who can. The page's script is run under node on a stub DOM with the platform's answers."""
import json
import shutil
import subprocess

import pytest

from conftest import ROOT

PAGE = ROOT / "homepage/evidence.html"

HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const [file, scenario] = process.argv.slice(2);
const html = fs.readFileSync(file, 'utf8'), s = JSON.parse(scenario);
class El {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {}; this.className = '';
                     this.hidden = false; this._text = ''; this.listeners = {}; this.style = {}; this.disabled = false;
                     this.href = ''; this.open = false; this.value = ''; }
  appendChild(c) { this.children.push(c); return c; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  set textContent(t) { this._text = String(t); this.children = []; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  contains() { return false; }
  all() { return this.children.flatMap((c) => c instanceof El ? [c, ...c.all()] : []); }
  querySelectorAll(sel) { return this.all().filter((c) => c.tagName === sel.toUpperCase()); }
}
const byId = {};
for (const m of html.replace(/<script[\s\S]*?<\/script>/gi, '').matchAll(/<(\w+)\b([^>]*)>/g)) {
  const id = /\bid="([^"]+)"/.exec(m[2]);
  if (id) { byId[id[1]] = new El(m[1]); byId[id[1]].hidden = /\shidden(\s|$)/.test(m[2]); }
}
const posts = [];
const answer = (status, body) => Promise.resolve({ok: status < 400, status, json: () => Promise.resolve(body),
                                                  text: () => Promise.resolve(JSON.stringify(body))});
function fetch(path, init) {
  if (init && init.method === 'POST') {
    posts.push({path, body: JSON.parse(init.body)});
    return s.again ? answer(s.again[0], s.again[1]) : Promise.reject(new Error('down'));
  }
  if (path === '/api/projects/demo') return answer(200, {name: 'Demo', pid: 'p-1'});
  if (path.startsWith('/api/projects/demo/evidence')) return answer(200, s.evidence);
  if (path === '/api/projects/demo/targets') return answer(200, {targets: [{kind: 'system', label: 'Demo', endpoint: {kind: 'openai'}}]});
  if (path.startsWith('/api/authz/')) return answer(200, {role: s.evidence.can_edit ? 'editor' : 'viewer'});
  return answer(200, {user: 'alice'});
}
const location = {search: s.search, href: '', replace() {}};
const document = {getElementById: (id) => byId[id] || null, createElement: (t) => new El(t),
                  createTextNode: (t) => ({textContent: String(t)}), querySelectorAll: () => [],
                  addEventListener() {}, title: ''};
const window = {aiscOriginsReady: Promise.resolve(), aiscOrigin: () => 'http://engine', aiscLink() {}};
const ctx = {document, fetch, window, URLSearchParams, encodeURIComponent, JSON, console, Date, location, Promise};
vm.createContext(ctx);
for (const m of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
  // the shared page.js, as the browser loads it (window's globals are the page's: aisc is window.aisc)
  if (/\bsrc="\/assets\/page\.js"/.test(m[1])) {
    vm.runInContext(fs.readFileSync(require('path').join(require('path').dirname(file), 'assets/page.js'), 'utf8'), ctx);
    ctx.aisc = window.aisc;
  } else if (/\bsrc="\/assets\/sandbox-gate\.js"/.test(m[1])) {
    vm.runInContext(fs.readFileSync(require('path').join(require('path').dirname(file), 'assets/sandbox-gate.js'), 'utf8'), ctx);
  } else if (!/\bsrc=/.test(m[1])) vm.runInContext(m[2], ctx);
}
const wait = () => new Promise((r) => setTimeout(r, 60));
(async () => {
  await wait();
  const box = byId['tile-deleted'];
  const out = {hidden: box.hidden, said: box.textContent, buttons: box.querySelectorAll('button').map((b) => b.textContent)};
  const button = box.querySelectorAll('button')[0];
  if (s.click && button) {
    button.listeners.click.forEach((fn) => fn({preventDefault() {}}));
    await wait();
    out.after = box.textContent;
    out.disabled = button.disabled;
  }
  out.posts = posts;
  out.went = location.href;
  console.log(JSON.stringify(out));
})();
"""

EVIDENCE = {
    "versions": [{"pid": "v2", "number": 2}], "version": {"pid": "v2", "number": 2},
    "can_edit": True, "can_review": False, "read_only": False, "carried_from": None, "review": None,
    "objectives": [], "tests": [], "controls": [], "links": [], "targets": [], "local_runs": [],
    "coverage": {"objectives": 0, "linked": 0, "gaps": 0},
    "plugins": [{"key": "aisc-plugin-langbite", "engine_name": "LangBiTePlugin", "label": "LangBiTe", "stale": None,
                 "runs": {"executed": 3, "failed": 0, "running": 0}}],
}
GONE = "aisc-plugin-langbite::LangBiTePlugin"


def run_page(tmp_path, search, *, can_edit=True, click=False, again=None):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    (tmp_path / "h.js").write_text(HARNESS)
    scenario = {"search": search, "evidence": {**EVIDENCE, "can_edit": can_edit}, "click": click, "again": again}
    r = subprocess.run(["node", str(tmp_path / "h.js"), str(PAGE), json.dumps(scenario)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout)


def test_the_page_says_the_tile_was_deleted_and_offers_to_make_it_again(tmp_path):
    seen = run_page(tmp_path, f"?project=demo&tile_deleted={GONE}")
    assert not seen["hidden"], seen
    assert "LangBiTe" in seen["said"] and "deleted" in seen["said"], seen
    assert seen["buttons"] == ["Make the tile again"], seen


def test_make_again_asks_the_platform_and_opens_the_new_tile(tmp_path):
    url = "http://dash/superset/dashboard/aisc-x/?aisc_project=p-1"
    seen = run_page(tmp_path, f"?project=demo&tile_deleted={GONE}", click=True, again=[200, {"url": url}])
    assert seen["posts"] == [{"path": "/api/projects/demo/dashboards/again", "body": {"plugin": GONE}}], seen
    assert seen["went"] == url, seen


def test_a_refused_make_again_says_the_platforms_reason(tmp_path):
    seen = run_page(tmp_path, f"?project=demo&tile_deleted={GONE}", click=True,
                    again=[502, {"detail": "the results dashboard did not answer: down"}])
    assert "the results dashboard did not answer" in seen["after"] and not seen["disabled"], seen
    assert seen["went"] == "", seen


def test_a_platform_that_does_not_answer_is_said_as_such(tmp_path):
    seen = run_page(tmp_path, f"?project=demo&tile_deleted={GONE}", click=True)
    assert "The platform is not answering." in seen["after"] and not seen["disabled"], seen


def test_a_viewer_is_told_who_can_make_it_again(tmp_path):
    seen = run_page(tmp_path, f"?project=demo&tile_deleted={GONE}", can_edit=False)
    assert seen["buttons"] == [] and "editor or owner" in seen["said"], seen


def test_without_a_deleted_tile_the_page_says_nothing_of_it(tmp_path):
    assert run_page(tmp_path, "?project=demo")["hidden"] is True
