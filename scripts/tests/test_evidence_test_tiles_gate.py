"""On the AI Assessment Sandbox page, each installed test's Configure and Run wait, like Run tests above them, until a
part of the AI system is connected: greyed out and not clickable, and back as they were once one is.

homepage/assets/sandbox-gate.js's aiscLockTestTiles does it on the tiles of the Run tests column. It is run here in
node on a small stand-in for the page's elements, as the browser would; the page's use of it is checked in its source.
"""
import json
import re
import shutil
import subprocess

import pytest

from conftest import ROOT

GATE_JS = ROOT / "homepage/assets/sandbox-gate.js"
SANDBOX = ROOT / "homepage/evidence.html"

# a stand-in for the column: tiles with their buttons; each step locks (false) or opens (true) them, and the
# buttons' attributes and classes after the last step are printed
_HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const [file, scenario] = process.argv.slice(1);
const s = JSON.parse(scenario);
function node(attrs, cls) {
  const a = Object.assign({}, attrs), c = new Set(cls || []), kids = [];
  return {
    kids,
    getAttribute: (k) => (k in a ? a[k] : null),
    setAttribute: (k, v) => { a[k] = String(v); },
    removeAttribute: (k) => { delete a[k]; },
    hasAttribute: (k) => k in a,
    classList: {add: (x) => c.add(x), remove: (x) => c.delete(x), contains: (x) => c.has(x)},
    querySelectorAll: (sel) => kids.filter((k) => k.matches(sel)),
    matches: (sel) => sel.split('.').slice(1).every((x) => c.has(x)),
    dump: () => ({attrs: a, classes: [...c].sort()}),
  };
}
const box = node({}, []);
const tiles = s.tiles.map((buttons) => {
  const tile = node({}, ['tile']);
  buttons.forEach((b) => tile.kids.push(node({href: b.href, title: b.title}, ['tile-btn', 'tile-open'])));
  box.kids.push(tile);
  return tile;
});
const window = {};
vm.runInNewContext(fs.readFileSync(file, 'utf8'), {window});
s.steps.forEach((open) => window.aiscLockTestTiles(box, open));
process.stdout.write(JSON.stringify(tiles.map((t) => ({tile: t.dump().classes, buttons: t.kids.map((b) => b.dump())}))));
"""

CONFIGURE = {"href": "https://app/projects/w/plugins/langbite?project=p", "title": "Configure LangBiTe"}
RUN = {"href": "https://app/projects/w/plugins/evaluation?project=p&plugin=langbite", "title": "Run LangBiTe"}


def lock(steps, tiles=((CONFIGURE, RUN),)):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", _HARNESS, str(GATE_JS),
                          json.dumps({"tiles": [list(t) for t in tiles], "steps": steps})],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_nothing_connected_greys_out_configure_and_run_and_makes_them_not_clickable():
    [tile] = lock([False])
    assert "is-off" in tile["tile"]
    for button in tile["buttons"]:
        assert "href" not in button["attrs"], "a link without href goes nowhere"
        assert button["attrs"]["aria-disabled"] == "true"
        assert "off" in button["classes"]
        assert button["attrs"]["title"].startswith("Connect at least one component")


def test_once_connected_the_buttons_come_back_as_they_were():
    [tile] = lock([False, True])
    assert "is-off" not in tile["tile"]
    assert [b["attrs"] for b in tile["buttons"]] == [CONFIGURE, RUN]
    assert all("off" not in b["classes"] for b in tile["buttons"])


def test_locked_twice_still_comes_back():
    [tile] = lock([False, False, True])
    assert [b["attrs"] for b in tile["buttons"]] == [CONFIGURE, RUN]


def test_open_leaves_fresh_tiles_untouched():
    [tile] = lock([True])
    assert tile["tile"] == ["tile"]
    assert [b["attrs"] for b in tile["buttons"]] == [CONFIGURE, RUN]


def test_every_tile_of_the_column_is_locked():
    tiles = lock([False], tiles=((CONFIGURE, RUN), (CONFIGURE,)))
    assert all("is-off" in t["tile"] for t in tiles)
    assert all("href" not in b["attrs"] for t in tiles for b in t["buttons"])


def scripts_of(html):
    return "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S | re.I))


def test_the_page_locks_the_test_tiles_when_it_gates_run_tests_and_after_drawing_them():
    html = SANDBOX.read_text()
    script = scripts_of(html)
    gate_ways = re.search(r"function gateWays.*?\n  }\n", script, re.S).group(0)
    assert "window.aiscLockTestTiles($('test-tiles'), gate.open)" in gate_ways
    render = re.search(r"function renderTiles.*?\n  }\n", script, re.S).group(0)
    assert "window.aiscLockTestTiles(box, testsOpen)" in render, "tiles drawn after the gate are locked too"
    assert re.search(r"a\.tile-btn\.off[^{]*\{[^}]*cursor:not-allowed", html), "the greyed button says it cannot be used"
