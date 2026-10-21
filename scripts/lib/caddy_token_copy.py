#!/usr/bin/env python3
"""Whether the gateway copies the person's access token onto every request it protects.

    python3 scripts/lib/caddy_token_copy.py [Caddyfile]      # exit 0 when it does, 1 when it doesn't

oauth2-proxy holds the session and passes its token back to Caddy (X-Auth-Request-Access-Token);
Caddy's forward_auth must copy that header onto the proxied request, or the modules behind the gateway
never see who is signed in. The `(protect)` snippet does this through the snippets it imports, so the
check follows those imports rather than looking at a fixed number of lines.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HEADER = "X-Auth-Request-Access-Token"


def snippets(text: str) -> dict[str, str]:
    """Every top-level `(name) { ... }` snippet of a Caddyfile, by name, with comments taken out."""
    lines = [re.sub(r"(^|\s)#.*$", "", line) for line in text.splitlines()]
    out, name, depth, body = {}, None, 0, []
    for line in lines:
        if name is None:
            m = re.match(r"^\(([\w-]+)\)\s*\{\s*$", line)
            if m:
                name, depth, body = m.group(1), 1, []
            continue
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            out[name] = "\n".join(body)
            name = None
        else:
            body.append(line)
    return out


def _imported(body: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r"^\s*import\s+([\w-]+)", body, re.M)]


def protect_copies_token(text: str) -> bool:
    """True when `(protect)`, or a snippet it imports (at any depth), forwards to oauth2-proxy and copies
    the access token header."""
    found = snippets(text)
    seen, todo = set(), ["protect"]
    while todo:
        name = todo.pop()
        if name in seen or name not in found:
            continue
        seen.add(name)
        body = found[name]
        auth = re.search(r"forward_auth\s+\S*:4180\s*\{(.*?)\n\s*\}", body, re.S)
        if auth and re.search(rf"^\s*copy_headers\b.*\b{re.escape(HEADER)}\b", auth.group(1), re.M):
            return True
        todo += _imported(body)
    return False


if __name__ == "__main__":
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "Caddyfile")
    sys.exit(0 if protect_copies_token(path.read_text()) else 1)
