"""The launcher's project pages say 'No such project' only when the platform says so (404).

A 500 from the platform, or a 502/503 while it restarts, used to read 'No such project: <slug>.' on every
project page, as if the project were gone. Each page's scripts are run under node with a permissive stub DOM;
every text the page puts on screen is collected."""
import json
import shutil
import subprocess

import pytest

from conftest import ROOT

PAGES = ["project.html", "helpers.html", "catalogue.html", "llm.html", "connectivity.html", "evidence.html",
         "connections.html", "results.html", "evidence-map.html"]

HARNESS = r"""
const fs = require('fs'), vm = require('vm'), path = require('path');
const [file, scenario] = process.argv.slice(2);
const html = fs.readFileSync(file, 'utf8'), s = JSON.parse(scenario);
process.on('unhandledRejection', () => {});
process.on('uncaughtException', () => {});
const shown = [];
// anything the page reaches for that the stub does not model is a no-op that can be called, read or chained
const any = new Proxy(function () {}, {get: (t, k) => k === Symbol.toPrimitive ? () => '' : any,
                                      apply: () => any, construct: () => any, set: () => true});
class El {
  constructor(tag) { this.tagName = String(tag || 'div').toUpperCase(); this.children = []; this._text = '';
                     this.hidden = false; this.value = ''; this.style = {}; this.dataset = {}; this.attrs = {};
                     this.classList = {add() {}, remove() {}, toggle() {}, contains: () => false};
                     return new Proxy(this, {get: (t, k) => k in t ? t[k] : any}); }
  get textContent() { return this._text + this.children.map((c) => c.textContent || '').join(''); }
  set textContent(v) { this._text = String(v); this.children = []; if (v) shown.push(String(v)); }
  get innerHTML() { return this._text; }
  set innerHTML(v) { this._text = String(v); if (v) shown.push(String(v)); }
  get innerText() { return this.textContent; }
  set innerText(v) { this.textContent = v; }
  appendChild(c) { this.children.push(c); return c; }
  append(...cs) { cs.forEach((c) => this.appendChild(typeof c === 'string' ? {textContent: c} : c)); }
  prepend(c) { this.children.unshift(c); }
  insertBefore(c) { this.children.push(c); return c; }
  replaceChildren(...cs) { this.children = []; this._text = ''; this.append(...cs); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener() {}
  querySelector() { return new El('div'); }
  querySelectorAll() { return []; }
  closest() { return null; }
  remove() {}
  showModal() {} close() {} focus() {} scrollIntoView() {}
}
const byId = {};
const document = {getElementById: (id) => byId[id] || (byId[id] = new El('div')), createElement: (t) => new El(t),
                  createTextNode: (t) => ({textContent: String(t)}), querySelector: () => new El('div'),
                  querySelectorAll: () => [], addEventListener() {}, body: new El('body'), title: '',
                  documentElement: new El('html'), cookie: ''};
function respond(status, body) {
  return Promise.resolve({ok: status < 400, status, json: () => Promise.resolve(body),
                          text: () => Promise.resolve(JSON.stringify(body)), headers: {get: () => null}});
}
function fetch(url) {
  const p = String(url);
  if (p.startsWith('/oauth2/')) return respond(200, {user: 'alice'});
  return respond(s.status, {detail: s.detail});
}
const ctx = {document, fetch, console: {log() {}, warn() {}, error() {}}, setTimeout, clearTimeout, setInterval() {},
             clearInterval() {}, URLSearchParams, URL, encodeURIComponent, decodeURIComponent, JSON, Promise, Date,
             Node: El, FormData: function () {}, navigator: {}, sessionStorage: any, localStorage: any,
             location: {pathname: '/' + path.basename(file), search: '?project=demo', hash: '', href: '',
                        origin: 'https://launcher.example', replace() {}, assign() {}},
             history: {replaceState() {}, pushState() {}}, confirm: () => false, alert() {},
             addEventListener() {}, removeEventListener() {}, matchMedia: () => ({matches: false, addEventListener() {}}),
             requestAnimationFrame: (f) => setTimeout(f, 0)};
ctx.window = ctx; ctx.self = ctx;
vm.createContext(ctx);
for (const m of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
  const src = /\bsrc="\/(assets\/[^"]+)"/.exec(m[1]);
  try { vm.runInContext(src ? fs.readFileSync(path.join(path.dirname(file), src[1]), 'utf8') : m[2], ctx); }
  catch (e) { /* a script that stops (no project, a missing stub) stops alone, as in a browser */ }
}
setTimeout(() => console.log(JSON.stringify(shown)), 150);
"""


def shown_on(tmp_path, page, status, detail):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    (tmp_path / "h.js").write_text(HARNESS)
    r = subprocess.run(["node", str(tmp_path / "h.js"), str(ROOT / "homepage" / page),
                        json.dumps({"status": status, "detail": detail})],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    return " | ".join(json.loads(r.stdout))


@pytest.mark.parametrize("page", PAGES)
@pytest.mark.parametrize("status", [500, 503])
def test_a_platform_failure_is_not_shown_as_no_such_project(tmp_path, page, status):
    shown = shown_on(tmp_path, page, status, "The platform could not reach its database")
    assert "No such project" not in shown, f"{page} on a {status} says: {shown}"
    assert "could not reach its database" in shown or str(status) in shown, \
        f"{page} on a {status} does not say what the platform answered: {shown}"


@pytest.mark.parametrize("page", PAGES)
def test_a_project_the_platform_does_not_know_still_reads_no_such_project(tmp_path, page):
    shown = shown_on(tmp_path, page, 404, "Not Found")
    assert "No such project" in shown, f"{page} on a 404 says: {shown}"
