"""JSON routes no page, the platform or any script called are gone: the pages ask the renderer and the built-in
layouts themselves."""
import pytest

GONE = [
    ("get", "/api/block-types"),
    ("get", "/api/fonts"),
    ("get", "/api/p/alpha/builtin-layouts"),
    ("get", "/api/p/alpha/builtin-layouts/builtin-summary"),
]


@pytest.mark.parametrize("method,path", GONE, ids=[p for _, p in GONE])
def test_the_route_is_gone(client, auth, method, path):
    assert getattr(client, method)(path, headers=auth("victor")).status_code in (404, 405)
