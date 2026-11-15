"""A host the platform cannot resolve is its own error, on every door: the plugin and the log read "dns" and
a message that names the host and the restart that cures a stale DNS, instead of "blocked" or a bare
connection error. The pure part needs no database; the door's answer runs on the throwaway."""
from __future__ import annotations

import logging
import socket


from platform_service import connection_facade as facade
from tests.conftest import needs_database
from tests.test_connection_facades import _env, base, connection, issue, keyed, stub  # noqa: F401  (fixtures)

UNRESOLVED = "no-such-host.invalid"


def interface():
    from aisc_plugin_interface import connections
    return connections


def name_not_resolved():
    found = getattr(facade, "name_not_resolved", None)
    assert found is not None, "the facade has no check for a host that does not resolve"
    return found


def _no_dns(host, port):
    raise socket.gaierror(-3, "Temporary failure in name resolution")


def test_a_host_that_does_not_resolve_is_its_own_error():
    c = interface()
    found = name_not_resolved()(c.BlockedAddress("h.example does not resolve"), "http://h.example:8080/x",
                                     resolve=_no_dns)
    assert isinstance(found, facade.NameNotResolved) and "h.example" in str(found)
    assert "restart the platform" in str(found)
    assert facade.ask_failure(found, []) == (502, {"error": "dns", "status": None, "detail": str(found)[:300]})


def test_a_host_that_resolves_keeps_its_own_error():
    c = interface()
    assert name_not_resolved()(c.EndpointError("L: refused"), "http://h:1", resolve=lambda h, p: [()]) is None


def test_only_address_and_connection_errors_are_checked():
    c = interface()
    asked = []
    assert name_not_resolved()(c.EndpointTimeout("L: slow"), "http://h:1",
                                    resolve=lambda h, p: asked.append(h)) is None
    assert asked == []


def test_the_error_codes_name_dns_last():
    assert facade.ERROR_CODES[-1] == ("NameNotResolved", "dns")


@needs_database
def test_a_connection_whose_host_does_not_resolve_says_so(client, admin, project, stub, monkeypatch, caplog):  # noqa: F811
    monkeypatch.setenv("CONNECTIONS_ALLOWED_HOSTS", f"{stub.host},{UNRESOLVED}")
    name = connection(client, admin, project, stub, base_url=f"http://{UNRESOLVED}:8080")
    key = issue(client, project, name).json()["key"]
    with caplog.at_level(logging.WARNING):
        r = client.post(f"{base(project, name)}/aisc/ask", json={"input": "q"}, headers=keyed(key))
    assert r.status_code == 502, r.text
    assert r.json()["error"] == "dns" and UNRESOLVED in r.json()["detail"], r.json()
    assert "(dns)" in caplog.text
