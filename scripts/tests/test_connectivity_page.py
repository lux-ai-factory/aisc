"""Manage > Connectivity (homepage/connectivity.html) and its one Manage entry, which replaces "AI assistant
models and keys", "Components and connections" and "Judges, attackers and other tool models". Static checks of
the page source, like test_connections_page.py."""
import re

from conftest import ROOT

PAGE = ROOT / "homepage/connectivity.html"
PROJECT_PAGE = ROOT / "homepage/project.html"
EVIDENCE_PAGE = ROOT / "homepage/evidence.html"


def read(path):
    assert path.is_file(), f"missing feature: {path.relative_to(ROOT)} does not exist"
    return path.read_text()


def script_of(html):
    return "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S | re.I))


def markup_of(html):
    return re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)


def manage_of(html):
    return re.search(r'<details[^>]*id="manage".*?</details>', html, re.S).group(0)


# ---- the Manage entry ----------------------------------------------------------------------------

def test_the_manage_menu_has_one_connectivity_entry_for_owners_and_admins():
    html = read(PROJECT_PAGE)
    manage = manage_of(html)
    link = re.search(r'<a\b[^>]*id="connectivity-settings"[^>]*>(.*?)</a>', manage, re.S)
    assert link and link.group(1).strip() == "Connectivity"
    tag = re.search(r'<a\b[^>]*id="connectivity-settings"[^>]*>', manage).group(0)
    assert "owner-only" in tag and "hidden" in tag, tag
    script = script_of(html)
    gate = script.index("if (a.admin || a.role === 'owner')")
    wiring = re.search(r"getElementById\('connectivity-settings'\)\.href\s*=\s*'/connectivity\.html\?project='\s*\+\s*"
                       r"encodeURIComponent\(slug\)", script)
    assert wiring and wiring.start() > gate, "the href is not set inside the owner block"
    assert script.find("if (!a.admin) return;") > wiring.start(), "the link must not wait for the admin-only part"


def test_the_three_old_entries_are_gone_from_both_menus():
    for page in (PROJECT_PAGE, EVIDENCE_PAGE):
        manage = manage_of(read(page))
        for old in ('id="llm-settings"', 'id="connections-settings"', 'id="helper-models"'):
            assert old not in manage, (page.name, old)


def test_the_evidence_page_menu_links_connectivity_like_the_project_page():
    script = script_of(read(EVIDENCE_PAGE))
    assert "$('connectivity-settings').href = '/connectivity.html?project=' + enc(slug)" in script


# ---- the page --------------------------------------------------------------------------------------

def test_the_page_has_its_four_tabs_in_order():
    html = markup_of(read(PAGE))
    tabs = re.findall(r'<button\b[^>]*role="tab"[^>]*data-tab="([a-z]+)"', html)
    assert tabs == ["assessed", "agents", "tools", "connections"]
    for tab in tabs:
        assert re.search(rf'<section\b[^>]*id="p-{tab}"[^>]*role="tabpanel"', html), tab


def test_the_page_reads_one_route_and_writes_only_through_the_platform():
    script = script_of(read(PAGE))
    assert "'/api/projects/' + enc(slug) + '/connectivity'" in script
    for write in ("'/agents/'", "'/tool'", "kind: 'provider'"):
        assert write in script, write
    assert "fetch(" in script and script.count("fetch(") == 1, "one request helper"


def test_the_page_never_shows_a_key():
    html = read(PAGE)
    assert re.search(r'<input[^>]*id="n-secret"[^>]*type="password"|<input[^>]*type="password"[^>]*id="n-secret"', html)
    for leak in ("secret_ciphertext", "api_key", ".secret)", ".secret;"):
        assert leak not in script_of(html), leak
    assignments = re.findall(r"\$\('n-secret'\)\.value\s*=(?!=)\s*([^;]*);", script_of(html))
    assert assignments and all(a.strip() == "''" for a in assignments), assignments


def test_the_assessed_system_is_marked_apart_and_its_editor_is_one_click_away():
    html = read(PAGE)
    assert "Every call to these is recorded" in html
    assert "'/connections.html?project=' + enc(slug)" in script_of(html)


def test_what_people_may_do_comes_from_the_platform():
    script = script_of(read(PAGE))
    assert "data.can_manage" in script
    assert "role === 'owner'" not in script, "the page does not decide roles itself"


def test_an_agents_model_is_chosen_from_the_providers_own_list():
    """The models the connection's provider offers, asked live with that connection's own address and key, are offered
    as the agent's model; a name the list lacks can still be typed."""
    script = script_of(read(PAGE))
    assert "'/connections/' + enc(c.name) + '/models'" in script
    assert "datalist" in script and ".setAttribute('list'" in script
    assert "change" in script and "fillModels" in script


def test_a_provider_whose_models_cannot_be_listed_leaves_the_name_to_type_and_says_why():
    script = script_of(read(PAGE))
    assert "type the model name" in script


def test_a_refused_new_provider_keeps_the_typed_key():
    """The key field is emptied only once the platform accepted the save: a refused one (a bad name, a name
    taken) leaves the key there to correct the rest and send again."""
    script = script_of(read(PAGE))
    handler = script.split("$('new-provider').addEventListener('submit'", 1)[1].split("\n  });", 1)[0]
    refused = handler.index("if (!r.ok)")
    assert "$('n-secret').value = ''" in handler
    assert handler.index("$('n-secret').value = ''") > refused


# ---- the page's script, run in node on the platform's answers ------------------------------------
# A small stand-in DOM: one element per id in the page's markup, the four tabs, and the elements the script makes.

_HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const [file, scenario] = process.argv.slice(2);
const html = fs.readFileSync(file, 'utf8'), s = JSON.parse(scenario);
class Node {}
class El extends Node {
  constructor(tag) { super(); this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {}; this.className = '';
                     this.hidden = false; this.value = ''; this._text = ''; this.listeners = {}; this.style = {}; }
  appendChild(c) { this.children.push(c); return c; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  set textContent(t) { this._text = String(t); this.children = []; }
  get options() { return this.children.filter((c) => c.tagName === 'OPTION'); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  all() { return this.children.flatMap((c) => c instanceof El ? [c, ...c.all()] : []); }
  querySelectorAll(sel) {
    return this.all().filter((c) => sel[0] === '.' ? c.className.split(' ').includes(sel.slice(1))
                                                   : c.tagName === sel.toUpperCase());
  }
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
                  createTextNode: (t) => new Text(t), querySelectorAll: (sel) => root.querySelectorAll(sel), title: ''};
function answer(path) {
  if (path === '/api/projects/demo') return {name: 'Demo'};
  if (path === '/api/projects/demo/connectivity') return s.connectivity;
  if (path.endsWith('/models')) return {models: [], error: 'not asked here'};
  return {};
}
function fetch(path) {
  const body = answer(path);
  return Promise.resolve({ok: true, status: 200, json: () => Promise.resolve(body)});
}
const ctx = {document, fetch, Node, URLSearchParams, encodeURIComponent, JSON, console,
             location: {search: '?project=demo', hash: '', replace() {}},
             history: {replaceState() {}}, window: {addEventListener() {}}};
vm.createContext(ctx);
for (const m of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)) vm.runInContext(m[1], ctx);
setTimeout(() => {
  const rows = (id) => byId[id].children.map((tr) => tr.children.map((td) => td.textContent));
  const texts = Object.values(byId).map((n) => n.textContent)
    .concat(root.all().flatMap((n) => [n.value, ...Object.values(n.attrs), n.href || '']));
  console.log(JSON.stringify({connections: rows('connections'), components: rows('components'), texts}));
}, 50);
"""


def _run_page(tmp_path, connectivity):
    import json
    import shutil
    import subprocess

    import pytest
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    harness = tmp_path / "harness.js"
    harness.write_text(_HARNESS)
    r = subprocess.run(["node", str(harness), str(PAGE), json.dumps({"connectivity": connectivity})],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout)


def _connectivity(connections, can_manage):
    return {"components": [{"key": "system", "kind": "system", "label": "Chatbot", "component_kind": None,
                            "file": None, "connection": {"name": "bot", "protocol": "HTTP", "last_test_ok": True}}],
            "agents": [{"id": "card", "label": "Card agent", "choice": None}],
            "tools": [{"role": "judge", "connections": [{"name": "openai", "label": "OpenAI"}]}],
            "connections": connections, "roles": ["judge", "attacker"],
            "providers": [{"id": "openai", "label": "OpenAI", "key_required": True, "base_url_editable": False}],
            "can_manage": can_manage}


_ADMIN_CONNECTIONS = [
    {"name": "bot", "label": "Bot", "kind": "http", "protocol": "HTTP", "provider": None,
     "base_url": "https://bot.example/chat", "has_secret": True,
     "target": {"key": "system", "kind": "system", "label": "Chatbot"}, "used_for": []},
    {"name": "openai", "label": "OpenAI", "kind": "provider", "protocol": "Provider", "provider": "openai",
     "base_url": None, "has_secret": True, "target": None, "used_for": [{"use": "tool", "roles": ["judge"]}]},
]
_OWNER_CONNECTIONS = [{k: c[k] for k in ("name", "label", "kind", "used_for")} for c in _ADMIN_CONNECTIONS]


def test_an_owner_sees_only_what_the_platform_gives_and_never_undefined(tmp_path):
    """An owner who is not an admin gets each connection's name, label, kind and uses only: the page shows those,
    with no "undefined" anywhere, and still marks the connection that reaches the assessed system (known from the
    components)."""
    out = _run_page(tmp_path, _connectivity(_OWNER_CONNECTIONS, can_manage=False))
    assert not [t for t in out["texts"] if "undefined" in str(t)], [t for t in out["texts"] if "undefined" in str(t)]
    bot, openai = out["connections"]
    assert bot[1] == "http" and openai[1] == "Provider"
    assert bot[2] == "" and bot[3] == "" and openai[3] == "", "no address or key state the owner was not given"
    assert "assessed: Chatbot" in bot[4]
    assert bot[5] == "(assessed)" and "tool: judge" in openai[4]


def test_an_admin_sees_every_setting_as_before(tmp_path):
    out = _run_page(tmp_path, _connectivity(_ADMIN_CONNECTIONS, can_manage=True))
    assert not [t for t in out["texts"] if "undefined" in str(t)]
    bot, openai = out["connections"]
    assert bot[:4] == ["Bot (bot)", "HTTP", "https://bot.example/chat", "stored"]
    assert openai[:4] == ["OpenAI (openai)", "Provider: openai", "", "stored"]
    assert "assessed: Chatbot" in bot[4] and bot[5] == "(assessed)"
