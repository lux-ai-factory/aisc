"""With the ledger witness off (LEDGER_GATEWAY unset), the gateway behaves exactly as it did before the
witness was added, apart from three intended changes: the header strip at the start of every protected
handle, the launcher's 404 for /api/authz/*, and the launcher's /add-controls/ (the add-controls service).

Both files are adapted by a real caddy:2.10.2 to JSON; the comparison ignores only those changes and
the extra nesting `route` adds. The baseline is the Caddyfile before the witness
(fixtures/ledger_gateway/Caddyfile.before-phase2): any later intended change to the gateway means
renewing this baseline on purpose, and reviewing that change.
"""
import json
import os
import shutil
import subprocess

import pytest

from conftest import ROOT

ENV = {"CADDY_DOMAIN": "http://localhost", "CADDY_PORT": "80", "HOMEPAGE_PORT": "8100", "DASHBOARD_PORT": "8008",
       "CADDY_ENVIRONMENT": "development", "LOG_FILE": "/tmp/caddy.log", "DASHBOARD_UPSTREAM": "host.docker.internal:8189"}
STRIPPED = {"X-Aisc-Request-Id", "X-Aisc-App", "X-Aisc-Gateway", "X-Aisc-Original-Uri", "X-Auth-Request-*",
            "X-Middleware-Subrequest"}


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
    # exactly the allow-list: every /api/authz/* path but the pages' role route
    if route.get("match") != [{"path": ["/api/authz/*"], "not": [{"path": ["/api/authz/projects/*"]}]}]:
        return False
    handlers = []
    for h in route.get("handle") or []:
        handlers.extend(r2 for r in (h.get("routes") or [{"handle": [h]}]) for r2 in r.get("handle") or [])
    return bool(handlers) and all(h.get("handler") == "static_response" and h.get("status_code") in (404, "404")
                                  for h in handlers)


def _is_add_controls(route):
    """The other intended change: the launcher's /add-controls/ (its redirect and its proxy to the
    add-controls service, which has its own login; test_add_controls.py)."""
    paths = [p for m in route.get("match") or [] for p in m.get("path") or []]
    return paths in (["/add-controls"], ["/add-controls/*"]) and "add-controls" in json.dumps(route.get("handle"))


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
            if isinstance(item, dict) and "handle" in item and (_is_authz(item) or _is_add_controls(item)):
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


def test_with_the_witness_unset_the_gateway_is_the_old_one_plus_the_strip_and_the_block(tmp_path):
    # since 2026-10-06 the sign-in is reached by its service name on the compose network
    # (test_no_host_network), not through the host: the one other change since phase 2
    old = (ROOT / "scripts/tests/fixtures/ledger_gateway/Caddyfile.before-phase2").read_text()
    (tmp_path / "Caddyfile").write_text(old.replace("host.docker.internal:4180", "oauth2-proxy:4180"))
    before = fixpoint(adapt(tmp_path / "Caddyfile"))
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
    ("    handle @caddy_only {\n      respond 404\n    }", "    handle @caddy_only {\n      reverse_proxy platform:8000\n    }"),
    # the allow-list widened to every /api/authz/* path but one more
    ("      not path /api/authz/projects/*\n", "      not path /api/authz/projects/* /api/authz/witness\n"),
    # the strip moved after sign-in, where it would delete oauth2-proxy's identity headers
    ("  request_header -X-Auth-Request-*\n  request_header -X-Middleware-Subrequest\n"
     "  forward_auth oauth2-proxy:4180 {",
     "  forward_auth oauth2-proxy:4180 {"),
])
def test_the_comparison_is_not_fooled_by_a_changed_strip_or_block(tmp_path, old, new):
    """Only a static 404 counts as the block, and only a strip before sign-in counts as the strip."""
    if "forward_auth oauth2-proxy:4180 {" in new and "request_header" not in new:
        text = _mutated(tmp_path, old, new).read_text()
        text = text.replace("      redir * /oauth2/start?rd={http.request.uri}\n    }\n  }\n",
                            "      redir * /oauth2/start?rd={http.request.uri}\n    }\n  }\n  request_header -X-Auth-Request-*\n"
                            "  request_header -X-Middleware-Subrequest\n", 1)
        (tmp_path / "Caddyfile").write_text(text)
        path = tmp_path / "Caddyfile"
    else:
        path = _mutated(tmp_path, old, new)
    before = fixpoint(adapt(ROOT / "scripts/tests/fixtures/ledger_gateway/Caddyfile.before-phase2"))
    assert json.dumps(fixpoint(adapt(path)), sort_keys=True) != json.dumps(before, sort_keys=True)
