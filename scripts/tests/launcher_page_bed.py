"""Runs a launcher page's scripts under node, as a browser would, against answers the test gives per path.

A small stand-in DOM records every text the page puts on screen, every button it makes (by its text) and every
call it makes to the platform. A scenario can click buttons by their text and type into fields by their
aria-label, in order, and then reads what the page shows and sent. Used by the work pages' tests.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from conftest import ROOT

HARNESS = r"""
const fs = require('fs'), vm = require('vm'), path = require('path');
const [file, scenario] = process.argv.slice(2);
const html = fs.readFileSync(file, 'utf8'), s = JSON.parse(scenario);
const shown = [], sent = [], made = [], errors = [];
process.on('unhandledRejection', (e) => errors.push(String(e && e.stack || e)));
class El {
  constructor(tag) { this.tagName = String(tag || 'div').toUpperCase(); this.children = []; this._text = '';
                     this.hidden = false; this.disabled = false; this.value = ''; this.style = {}; this.dataset = {};
                     this.attrs = {}; this.listeners = {}; this.className = ''; this.href = '';
                     this.classList = {add() {}, remove() {}, toggle() {}, contains: () => false}; made.push(this); }
  get textContent() { return this._text + this.children.map((c) => c.textContent || '').join(''); }
  set textContent(v) { this._text = String(v); this.children = []; if (v) shown.push(String(v)); }
  get innerHTML() { return this._text; }
  set innerHTML(v) { this._text = String(v); this.children = []; if (v) shown.push(String(v)); }
  appendChild(c) { this.children.push(c); return c; }
  append(...cs) { cs.forEach((c) => this.appendChild(typeof c === 'string' ? new Text(c) : c)); }
  replaceChildren(...cs) { this.children = []; this._text = ''; this.append(...cs); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  addEventListener(type, f) { (this.listeners[type] = this.listeners[type] || []).push(f); }
  querySelector() { return new El('div'); }
  querySelectorAll() { return []; }
  remove() {}
  focus() {}
}
class Text { constructor(t) { this.textContent = String(t); shown.push(String(t)); } }
const byId = {};
// an element of the page's own markup has the tag the markup gives it
const tagOf = (id) => { const m = new RegExp('<(\\w+)[^>]*\\bid="' + id + '"').exec(html); return m ? m[1] : 'div'; };
const document = {getElementById: (id) => byId[id] || (byId[id] = new El(tagOf(id))), createElement: (t) => new El(t),
                  createTextNode: (t) => new Text(t), querySelector: () => new El('div'),
                  querySelectorAll: () => [], addEventListener() {}, body: new El('body'), title: ''};
function answerFor(p) {
  const keys = Object.keys(s.answers || {}).sort((a, b) => b.length - a.length);
  const key = keys.find((k) => p === k || p.split('?')[0] === k);
  return key ? s.answers[key] : {status: 404, body: {detail: 'Not Found'}};
}
function fetch(url, init) {
  const p = String(url);
  init = init || {};
  if (p.startsWith('/oauth2/') || p === '/origins.json') {
    return Promise.resolve({ok: true, status: 200, json: () => Promise.resolve({user: 'me'}),
                            text: () => Promise.resolve('{"user": "me"}')});
  }
  sent.push({path: p, method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : null});
  const a = answerFor(p);
  const text = JSON.stringify(a.body === undefined ? null : a.body);
  return Promise.resolve({ok: a.status < 400, status: a.status, json: () => Promise.resolve(a.body),
                          text: () => Promise.resolve(text)});
}
const ctx = {document, fetch, console: {log() {}, warn() {}, error: (e) => errors.push(String(e))}, setTimeout,
             clearTimeout, setInterval() {}, clearInterval() {}, URLSearchParams, URL, encodeURIComponent,
             decodeURIComponent, JSON, Promise, Date, Number, String, Object, Array, Math,
             location: {pathname: s.pathname || ('/' + path.basename(file)), search: s.search || '', hash: '',
                        href: '', protocol: 'https:', hostname: 'launcher.example', replace() {}, assign() {}},
             confirm: () => true, alert() {}, addEventListener() {}, removeEventListener() {}};
ctx.window = ctx;
vm.createContext(ctx);
for (const m of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
  const src = /\bsrc="\/(assets\/[^"]+)"/.exec(m[1]);
  try { vm.runInContext(src ? fs.readFileSync(path.join(path.dirname(file), src[1]), 'utf8') : m[2], ctx); }
  catch (e) { errors.push(String(e && e.stack || e)); }
}
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
// what is on the page now: everything reachable from the page's own elements (a list drawn again drops the old)
function onPage() {
  const seen = new Set();
  const walk = (n) => { if (!n || seen.has(n)) return; seen.add(n); (n.children || []).forEach(walk); };
  Object.values(byId).forEach(walk);
  return made.filter((e) => seen.has(e));
}
const buttons = () => onPage().filter((e) => e.tagName === 'BUTTON' && !e.hidden);
(async () => {
  await wait(80);
  for (const step of s.steps || []) {
    if (step.type) {
      const field = onPage().find((e) => e.attrs['aria-label'] === step.type);
      if (!field) { errors.push('no field ' + step.type); continue; }
      field.value = step.value;
    } else if (step.click) {
      const button = buttons().find((b) => b.textContent === step.click && !b.disabled);
      if (!button) { errors.push('no button ' + step.click); continue; }
      (button.listeners.click || []).forEach((f) => f({preventDefault() {}, target: button}));
      await wait(80);
    }
  }
  console.log(JSON.stringify({shown, sent, buttons: buttons().map((b) => b.textContent),
                              links: onPage().filter((e) => e.tagName === 'A' && e.href).map((e) => [e.textContent, e.href]),
                              errors}));
})();
"""


def run_page(tmp_path, page: str, **scenario) -> dict:
    """What `page` (a file in homepage/) shows, sent and offered under `scenario`: answers ({path: {status,
    body}}), search ('?project=demo'), steps ([{"type": aria-label, "value": ...} | {"click": text}])."""
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    harness = tmp_path / "page-bed.js"
    harness.write_text(HARNESS)
    r = subprocess.run(["node", str(harness), str(ROOT / "homepage" / page), json.dumps(scenario)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout)
