"""The Caddyfile's ledger witness, read as text. What it must say, from how a real Caddy orders
directives:

- `protect` wraps everything in `route`, or Caddy runs the witness before sign-in and the strip after
  the witness;
- it strips client-sent identity and request-id headers before anything else;
- the witness snippet is chosen by LEDGER_GATEWAY, called on writes only, with the gateway secret, the
  app the handle names and the unstripped URI;
- every handle that serves anything imports `protect` with the right app, and the launcher never serves
  `/api/authz/*`.

The behaviour itself is checked on a real Caddy by test_ledger_gateway.py.
"""
import re
import sys

from conftest import ROOT

sys.path.insert(0, str(ROOT / "platform"))

import os
from pathlib import Path

#: LEDGER_TEST_CADDYFILE checks another file instead of the repo's Caddyfile.
CADDYFILE = Path(os.environ.get("LEDGER_TEST_CADDYFILE", ROOT / "Caddyfile")).read_text()
STRIPS = ["-X-AISC-Request-Id", "-X-AISC-App", "-X-AISC-Gateway", "-X-AISC-Original-Uri", "-X-Auth-Request-*"]

#: (site, handle) -> the app its `import protect` must name. Sites: 1 main, 2 launcher, 3 dashboard.
EXPECTED_APP = {
    (1, "handle /api/*"): "engine",
    (1, "handle /flower/*"): "flower",
    (1, "handle /controls*"): "controls",
    (1, "handle /qualification*"): "qualification",
    (1, "handle_path /control-objectives*"): "control_objectives",
    (1, "handle_path /report-composer*"): "report_composer",
    (1, "handle @platformProjects"): "platform",
    (1, "handle"): "engine_webapp",
    (2, "handle_path /api/*"): "platform",
    (2, "handle /p/*"): "launcher",
    (2, "handle /inspect/pgadmin*"): "pgadmin",
    (2, "handle_path /inspect/schema*"): "schema",
    (2, "handle"): "launcher",
    (3, "handle"): "dashboard",
}
#: Handles that answer without reaching anything: they must never proxy or serve files.
REFUSING = {(1, "handle /api/v1/internal/*"), (2, "handle /api/internal/*"), (2, "handle @caddy_only")}


def blocks(text: str):
    """(header, body, start) of every brace block. A `{` opens a block only at the end of its line, so
    placeholders like {http.request.uri} or {$CADDY_DOMAIN} never count."""
    out, stack, pos = [], [], 0
    for line in text.splitlines(keepends=True):
        stripped = line.split("#", 1)[0].rstrip()
        if stripped.endswith("{") and not stripped.endswith("${"):
            stack.append((stripped[:-1].strip(), pos + len(line)))
        elif stripped.strip() == "}" and stack:
            header, start = stack.pop()
            out.append((header, text[start:pos], start))
        pos += len(line)
    return out


def snippet(name: str) -> str:
    found = [b for h, b, _ in blocks(CADDYFILE) if h == f"({name})"]
    assert found, f"no ({name}) snippet"
    return found[0]


def sites():
    """The three site blocks, in file order, with their innermost handles."""
    tops = [(h, b, s) for h, b, s in blocks(CADDYFILE) if h.startswith("{$CADDY_DOMAIN}")]
    assert len(tops) == 3, [h for h, _, _ in tops]
    out = []
    for n, (_, body, _) in enumerate(sorted(tops, key=lambda t: t[2]), 1):
        handles = [(h, b) for h, b, _ in blocks(body) if re.match(r"handle(_path)?\b", h)]
        out.append((n, handles))
    return out


def directives(body: str) -> list[str]:
    return [line.strip() for line in body.splitlines() if line.strip() and not line.strip().startswith("#")]


def test_protect_wraps_its_directives_in_route():
    body = directives(snippet("protect"))
    assert body and body[0] == "route {", "protect must start with `route {` (06-spike.md G7)"


def test_protect_strips_client_headers_before_anything_else():
    assert directives(snippet("protect"))[1] == "import strip-and-sign-in", "the strip comes first in protect"
    lines = directives(snippet("strip-and-sign-in"))
    first_auth = next(i for i, line in enumerate(lines) if line.startswith("forward_auth"))
    for strip in STRIPS:
        at = [i for i, line in enumerate(lines) if line == f"request_header {strip}"]
        assert at and at[0] < first_auth, f"protect must strip {strip} before forward_auth"


def test_sign_in_comes_before_the_witness():
    assert "/oauth2/auth" in snippet("strip-and-sign-in")
    body = snippet("protect")
    assert body.index("import strip-and-sign-in") < body.index("import witness-{$LEDGER_GATEWAY:off} {args[0]}")


def test_the_witness_snippet_is_chosen_by_ledger_gateway():
    assert directives(snippet("witness-off")) == []
    on = snippet("witness-on")
    assert re.search(r"@witnessed_\{args\[0\]\}\s*\{\s*not method GET HEAD OPTIONS\s*\}", on)
    witness = [b for h, b, _ in blocks(on) if h == "forward_auth @witnessed_{args[0]} platform:8000"]
    assert witness, "the witness forward_auth must use the writes-only matcher"
    lines = directives(witness[0])
    for needed in ["uri /authz/witness", "header_up X-AISC-App {args[0]}",
                   "header_up X-AISC-Original-Uri {http.request.orig_uri}",
                   "header_up X-AISC-Gateway {$AISC_WITNESS_GATEWAY_SECRET}", "copy_headers X-AISC-Request-Id"]:
        assert needed in lines, f"witness-on lacks `{needed}`"


def test_every_serving_handle_imports_protect_with_its_app():
    from platform_service.ledger.registry import KNOWN_APPS

    seen, problems = set(), []
    for site, handles in sites():
        for header, body in handles:
            if any(re.match(r"handle(_path)?\b", h) for h, _, _ in blocks(body)):
                continue                                          # only the innermost handles serve
            key = (site, header)
            if key in REFUSING or header == "handle /oauth2/*":
                continue
            if not re.search(r"^\s*(reverse_proxy|file_server)\b", body, re.M):
                continue
            seen.add(key)
            imports = re.findall(r"^\s*import (protect|protect-reads)\s(.*)$", body, re.M)
            checks = re.findall(r"^\s*import (admin_only|schema_gate)\s*$", body, re.M)
            if checks:                                   # a check must share protect's route (Caddy order)
                routed = [b for h, b, _ in blocks(body) if h == "route"]
                if not any(f"import {checks[0]}" in b and "import protect" in b for b in routed):
                    problems.append(f"{key}: {checks[0]} is outside protect's route: it would run before sign-in")
            if len(imports) != 1:
                problems.append(f"{key}: {len(imports)} `import protect`")
                continue
            kind, args = imports[0][0], imports[0][1].split()
            if kind == "protect-reads" and not (len(args) > 1 and all(a.startswith("/") for a in args[1:])):
                problems.append(f"{key}: protect-reads needs the read paths (an empty list fails at load, S1)")
            if args[:1] != [EXPECTED_APP.get(key, "?")] or (kind == "protect" and len(args) != 1):
                problems.append(f"{key}: imports protect {args}, expected {EXPECTED_APP.get(key)}")
            elif args[0] not in KNOWN_APPS:
                problems.append(f"{key}: {args[0]} is not in KNOWN_APPS")
    assert not problems, "\n".join(problems)
    assert seen == set(EXPECTED_APP), f"handles changed: {sorted(seen ^ set(EXPECTED_APP))}"


def test_refusing_handles_never_serve():
    found = set()
    for site, handles in sites():
        for header, body in handles:
            if (site, header) in REFUSING:
                found.add((site, header))
                assert re.search(r"^\s*respond\b", body, re.M), header
                assert not re.search(r"^\s*(reverse_proxy|file_server)\b", body, re.M), header
    assert found == REFUSING, f"missing refusing handles: {sorted(REFUSING - found)}"


def test_the_launcher_blocks_the_witness_before_its_api():
    launcher = dict(sites())[2]
    order = [h for h, _ in launcher]
    assert order.index("handle @caddy_only") < order.index("handle_path /api/*")


def test_protect_reads_is_protect_plus_listed_reads():
    """The same strip and sign-in, then the write witness and a GET witness on the listed paths."""
    body = snippet("protect-reads")
    assert directives(body)[0] == "route {"
    assert "import strip-and-sign-in" in body and "import strip-and-sign-in" in snippet("protect")
    assert "import witness-{$LEDGER_GATEWAY:off} {args[0]}" in body
    assert "import witness-reads-{$LEDGER_GATEWAY:off} {args[0:]}" in body
    assert directives(snippet("witness-reads-off")) == []
    on = snippet("witness-reads-on")
    assert re.search(r"@witnessed_reads_\{args\[0\]\}\s*\{\s*method GET\s+path \{args\[1:\]\}\s*\}", on)


def test_oauth_endpoints_stay_open():
    assert "handle /oauth2/*" in snippet("oauth_endpoints")
    assert "import protect" not in snippet("oauth_endpoints")


def test_read_paths_are_written_as_the_handle_sees_them():
    """handle_path strips its prefix before the matcher runs, so a read path under it is written without the
    prefix; under handle it keeps it. A path with the stripped prefix would never match, and every read it
    should witness would go unwitnessed."""
    problems = []
    for site, handles in sites():
        for header, body in handles:
            m = re.match(r"handle(_path)?\s+(\S+?)\*?$", header)
            reads = re.findall(r"^\s*import protect-reads \S+ (.+)$", body, re.M)
            if not m or not reads:
                continue
            stripped, prefix = bool(m.group(1)), m.group(2).rstrip("*")
            for path in reads[0].split():
                if stripped and path.startswith(prefix + "/"):
                    problems.append(f"{header}: {path} keeps the prefix handle_path strips")
                if not stripped and not path.startswith(prefix):
                    problems.append(f"{header}: {path} is outside the handle's {prefix}")
    assert not problems, "\n".join(problems)
