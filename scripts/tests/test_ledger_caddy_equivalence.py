"""With the witness off (LEDGER_GATEWAY unset, as on a live Caddy restarted after phase 2), the gateway
behaves exactly as before phase 2, apart from the two intended changes: the header strip at the start
of every protected handle, and the launcher's 404 for /api/authz/* (phase 2 review m13).

Both files are adapted by a real caddy:2.10.2 to JSON; the comparison ignores only those two changes and
the extra nesting `route` adds. The baseline is the Caddyfile before phase 2
(fixtures/ledger_gateway/Caddyfile.before-phase2): a later intended change to the gateway means this
test's baseline is renewed on purpose, with the review that change gets.
"""
import json
import os
import shutil
import subprocess

import pytest

from conftest import ROOT

ENV = {"CADDY_DOMAIN": "http://localhost", "CADDY_PORT": "80", "HOMEPAGE_PORT": "8100", "DASHBOARD_PORT": "8008",
       "CADDY_ENVIRONMENT": "development", "LOG_FILE": "/tmp/caddy.log", "DASHBOARD_UPSTREAM": "host.docker.internal:8189"}
STRIPPED = {"X-Aisc-Request-Id", "X-Aisc-App", "X-Aisc-Gateway", "X-Aisc-Original-Uri", "X-Auth-Request-*"}


def adapt(path):
    if not shutil.which("docker"):
        if os.environ.get("LEDGER_TESTS_REQUIRED") == "1":
            pytest.fail("LEDGER_TESTS_REQUIRED=1 but docker is not available")
        pytest.skip("docker is not available")
    envs = [a for k, v in ENV.items() for a in ("-e", f"{k}={v}")]
    r = subprocess.run(["docker", "run", "--rm", *envs, "-v", f"{path}:/C:ro", "caddy:2.10.2", "caddy", "adapt",
                        "--config", "/C", "--adapter", "caddyfile"], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout)


def _is_strip(handler):
    deleted = (handler.get("request") or {}).get("delete") or []
    return handler.get("handler") == "headers" and bool(deleted) and \
        {d.lower() for d in deleted} <= {s.lower() for s in STRIPPED}


def _is_authz(route):
    """Only the intended block: /api/authz/* answered by a static 404 and nothing else."""
    if not any("/api/authz/*" in (m.get("path") or []) for m in route.get("match") or []):
        return False
    handlers = []
    for h in route.get("handle") or []:
        handlers.extend(r2 for r in (h.get("routes") or [{"handle": [h]}]) for r2 in r.get("handle") or [])
    return bool(handlers) and all(h.get("handler") == "static_response" and h.get("status_code") in (404, "404")
                                  for h in handlers)


def _is_sign_in(handler):
    """oauth2-proxy's forward_auth, as Caddy adapts it: a reverse_proxy to port 4180."""
    return isinstance(handler, dict) and handler.get("handler") == "reverse_proxy" and \
        any(str(u.get("dial", "")).endswith(":4180") for u in handler.get("upstreams") or [])


def normal(node):
    """Drop the intended changes and flatten match-less subroutes, until nothing changes."""
    if isinstance(node, list):
        out = []
        for i, item in enumerate(node):
            if isinstance(item, dict) and _is_strip(item):
                # only a strip in the run of strips right before sign-in is the intended one
                rest = node[i + 1:]
                following = next((h for h in rest if not (isinstance(h, dict) and _is_strip(h))), None)
                if _is_sign_in(following):
                    continue
            if isinstance(item, dict) and "handle" in item and _is_authz(item):
                continue
            if isinstance(item, dict) and item.get("handler") == "subroute" and \
                    all("match" not in r for r in item.get("routes") or []):
                for r in item["routes"]:
                    out.extend(normal(r.get("handle") or []))
                continue
            out.append(normal(item))
        return out
    if isinstance(node, dict):
        return {k: normal(v) for k, v in node.items()}
    return node


def relabel(node, names=None):
    """Caddy numbers the groups it makes (group35, group52, ...); the numbers depend on how many
    snippets came before, the grouping itself is what matters. Renumber by first appearance."""
    names = {} if names is None else names
    if isinstance(node, list):
        return [relabel(item, names) for item in node]
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k == "group" and isinstance(v, str):
                out[k] = names.setdefault(v, f"g{len(names)}")
            else:
                out[k] = relabel(v, names)
        return out
    return node


def fixpoint(tree):
    while True:
        nxt = normal(tree)
        if nxt == tree:
            return relabel(tree)
        tree = nxt


def test_with_the_witness_unset_the_gateway_is_the_old_one_plus_the_strip_and_the_block():
    before = fixpoint(adapt(ROOT / "scripts/tests/fixtures/ledger_gateway/Caddyfile.before-phase2"))
    after = fixpoint(adapt(ROOT / "Caddyfile"))
    assert json.dumps(after, sort_keys=True) == json.dumps(before, sort_keys=True)


def test_the_strip_and_the_block_are_really_there():
    raw = json.dumps(adapt(ROOT / "Caddyfile"))
    assert raw.count('"X-Aisc-Request-Id"') + raw.count('"X-AISC-Request-Id"') >= 14
    assert "/api/authz/*" in raw


def _mutated(tmp_path, old, new):
    text = (ROOT / "Caddyfile").read_text()
    assert old in text, old
    path = tmp_path / "Caddyfile"
    path.write_text(text.replace(old, new, 1))
    return path


@pytest.mark.parametrize("old, new", [
    # the launcher's witness block proxying instead of refusing
    ("    handle /api/authz/* {\n      respond 404\n    }", "    handle /api/authz/* {\n      reverse_proxy platform:8000\n    }"),
    # the strip moved after sign-in, where it would delete oauth2-proxy's identity headers
    ("  request_header -X-Auth-Request-*\n  forward_auth host.docker.internal:4180 {",
     "  forward_auth host.docker.internal:4180 {"),
])
def test_the_comparison_is_not_fooled_by_a_changed_strip_or_block(tmp_path, old, new):
    """Phase 2 re-review n2: only a static 404 counts as the block, only a strip before sign-in as the strip."""
    if "forward_auth host.docker.internal:4180 {" in new and "request_header" not in new:
        text = _mutated(tmp_path, old, new).read_text()
        text = text.replace("      redir * /oauth2/start?rd={http.request.uri}\n    }\n  }\n",
                            "      redir * /oauth2/start?rd={http.request.uri}\n    }\n  }\n  request_header -X-Auth-Request-*\n", 1)
        (tmp_path / "Caddyfile").write_text(text)
        path = tmp_path / "Caddyfile"
    else:
        path = _mutated(tmp_path, old, new)
    before = fixpoint(adapt(ROOT / "scripts/tests/fixtures/ledger_gateway/Caddyfile.before-phase2"))
    assert json.dumps(fixpoint(adapt(path)), sort_keys=True) != json.dumps(before, sort_keys=True)
