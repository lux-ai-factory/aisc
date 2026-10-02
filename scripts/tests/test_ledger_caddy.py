"""C2: nothing reaches an app without passing the witness (I1).

The witness is a second forward_auth inside Caddy's `protect` snippet, so every module that imports
`protect` is witnessed. These checks read the Caddyfile: the snippet calls the witness and forwards its
request id, and every handle that proxies to a module imports `protect`, except the reviewed ones
(the sign-in endpoints and the service-token routes, which carry no person).
"""
import re

from conftest import ROOT

CADDYFILE = (ROOT / "Caddyfile").read_text()

#: Handles that proxy without `protect`, and why.
UNPROTECTED = {
    "/oauth2/*": "oauth2-proxy's own endpoints: the way in",
    "/api/v1/internal/*": "the engine's service-token routes: no person, its events come by the internal route",
    "/api/internal/*": "the platform's service-token routes: no person, its events come by the internal route",
}


def blocks(text: str):
    """(header, body) of every brace block, nested blocks included."""
    out, stack = [], []
    for i, ch in enumerate(text):
        if ch == "{":
            line_start = text.rfind("\n", 0, i) + 1
            stack.append((text[line_start:i].strip(), i))
        elif ch == "}" and stack:
            header, start = stack.pop()
            out.append((header, text[start + 1:i]))
    return out


def snippet(name: str) -> str:
    match = re.search(r"^\(" + re.escape(name) + r"\)\s*\{", CADDYFILE, re.M)
    assert match, f"no ({name}) snippet"
    body = next(b for h, b in blocks(CADDYFILE[match.start():]) if h == f"({name})")
    return body


def test_the_protect_snippet_calls_the_witness_and_forwards_its_request_id():
    body = snippet("protect")
    witness = [b for h, b in blocks(body) if h.startswith("forward_auth platform:8000")]
    assert any(re.search(r"^\s*uri\s+/authz/witness\b", b, re.M) for b in witness), \
        "the protect snippet has no forward_auth to the platform's /authz/witness"
    assert any(re.search(r"copy_headers\s+.*X-AISC-Request-Id", b) for b in witness)


def test_the_witness_comes_after_sign_in():
    body = snippet("protect")
    assert body.index("/oauth2/auth") < body.index("/authz/witness"), \
        "the witness must see the token oauth2-proxy has just checked"


def test_every_proxied_handle_is_protected_or_a_reviewed_exception():
    unprotected = []
    for header, body in blocks(CADDYFILE):
        if not header.startswith(("handle", "handle_path")):
            continue
        if "reverse_proxy" not in body or any(h.startswith(("handle", "handle_path")) for h, _ in blocks(body)):
            continue                                      # only the innermost handles proxy
        path = header.split()[1] if len(header.split()) > 1 else "(catch-all)"
        if "import protect" not in body and path not in UNPROTECTED:
            unprotected.append(header)
    assert not unprotected, "handles proxying without the witness:\n" + "\n".join(unprotected)


def test_every_reviewed_exception_still_exists():
    headers = {h.split()[1] for h, _ in blocks(CADDYFILE) if h.startswith(("handle ", "handle_path ")) and len(h.split()) > 1}
    for path in UNPROTECTED:
        assert path in headers, f"{path} is a reviewed exception but no longer in the Caddyfile"
