"""Routes nothing called are gone: no page, application or script used them, and each kept code alive for nothing.
A route that exists answers an anonymous call with 401; one that is gone is not found."""
import pytest

GONE = [
    ("GET", "/projects/p/catalogue/api/tool/1/tags/"),
    ("GET", "/projects/p/catalogue/api/metadata/"),
    ("POST", "/projects/p/connections/chat/link"),
    ("GET", "/systems/00000000-0000-0000-0000-000000000000"),
    ("GET", "/projects/p/ledger/events/1"),
    ("POST", "/projects/p/dashboards/sync"),
]


@pytest.mark.parametrize("method,path", GONE, ids=[f"{m} {p}" for m, p in GONE])
def test_the_route_is_gone(client, method, path):
    assert client.request(method, path).status_code in (404, 405)


def test_the_helpers_only_those_routes_used_are_gone():
    from platform_service import catalogue, connection_store, db

    for module, name in ((catalogue, "tool_tags"), (catalogue, "metadata"), (connection_store, "record_link"),
                         (db, "get_system")):
        assert not hasattr(module, name), f"{module.__name__}.{name}"
