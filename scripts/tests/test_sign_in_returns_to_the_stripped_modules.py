"""Opening a page of a module served under handle_path (the report composer, control objectives) before signing
in must bring the person back to that page after sign-in. handle_path strips the module's prefix before the
sign-in check runs, so a sign-in redirect built from the request's current URI sends the person to the path
without the prefix, which the engine's frontend answers with 404.

Runs the repo's Caddyfile on a real Caddy with stub upstreams (the bed of test_ledger_gateway.py); the stub
sign-in answers 401 for a request whose X-Test header contains "unauth"."""
import urllib.error
import urllib.parse
import urllib.request
import uuid

import pytest

from test_ledger_gateway import PORTS, gateway  # noqa: F401  (the real-Caddy bed)

PAGES = [
    "/report-composer/p/mcas/layouts/0b5446b0-3bcf-4747-9a47-996747111b86",
    "/control-objectives/p/mcas/projects/a1",
]


def _sign_in_redirect(path):
    port = PORTS["main"]
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 headers={"Host": f"localhost:{port}", "X-Test": f"unauth-{uuid.uuid4().hex}"})

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    try:
        r = urllib.request.build_opener(NoRedirect).open(req, timeout=10)
        return r.status, r.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location", "")


@pytest.mark.parametrize("path", PAGES)
def test_signing_in_from_a_module_page_comes_back_to_that_page(gateway, path):  # noqa: F811
    status, location = _sign_in_redirect(path)
    assert status in (302, 303, 307), (status, location)
    target = urllib.parse.urlparse(location)
    assert target.path == "/oauth2/start", location
    back_to = urllib.parse.parse_qs(target.query).get("rd", [""])[0]
    assert back_to == path, f"sign-in sends the person back to {back_to!r}, not to {path!r}"
