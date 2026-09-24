"""fetch_text: every redirect hop is re-checked against the metadata guard, and the whole
download is bounded by a wall-clock deadline (task 6 fix, spec D7)."""
from __future__ import annotations

import ipaddress
import socket

import httpx
import pytest
import respx

from aisc_connectors.executor.errors import GatewayFailure
from aisc_connectors.executor.guard import refuse_metadata_host
from aisc_connectors.importers import fetch as fetch_module
from aisc_connectors.importers.errors import ImportFailed
from aisc_connectors.importers.fetch import fetch_text


def _fake_getaddrinfo(ordinary_ip="93.184.216.34"):
    """DNS stand-in: a literal IP host resolves to itself, anything else to an ordinary
    public IP, so tests never touch real DNS."""

    def getaddrinfo(host, *_args, **_kwargs):
        try:
            ipaddress.ip_address(host)
            resolved = host
        except ValueError:
            resolved = ordinary_ip
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (resolved, 0))]

    return getaddrinfo


def test_a_redirect_to_a_metadata_host_is_refused(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo())
    with respx.mock(assert_all_called=False) as router:
        metadata_route = router.get("http://169.254.169.254/latest").mock(
            return_value=httpx.Response(200, text="leaked")
        )
        router.get("http://good.example/spec.json").mock(
            return_value=httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})
        )
        with pytest.raises((ImportFailed, GatewayFailure)):
            fetch_text("http://good.example/spec.json")
        assert not metadata_route.called


def test_a_redirect_to_an_ordinary_host_is_followed(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo())
    with respx.mock() as router:
        router.get("http://good.example/spec.json").mock(
            return_value=httpx.Response(302, headers={"location": "http://also-good.example/real.json"})
        )
        router.get("http://also-good.example/real.json").mock(return_value=httpx.Response(200, text='{"ok": true}'))
        assert fetch_text("http://good.example/spec.json") == '{"ok": true}'


def test_six_redirects_fail(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo())
    hosts = [f"http://hop{i}.example/spec.json" for i in range(7)]
    with respx.mock() as router:
        for current, nxt in zip(hosts, hosts[1:]):
            router.get(current).mock(return_value=httpx.Response(302, headers={"location": nxt}))
        with pytest.raises(ImportFailed, match="too many redirects"):
            fetch_text(hosts[0])


def test_the_overall_download_is_bounded_to_30_seconds(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo())
    calls = iter([0.0, 31.0])
    monkeypatch.setattr(fetch_module.time, "monotonic", lambda: next(calls, 31.0))
    with pytest.raises(ImportFailed, match="30 s"):
        fetch_text("http://good.example/spec.json")


def test_ipv4_mapped_ipv6_metadata_addresses_are_refused(monkeypatch):
    def getaddrinfo(host, *_args, **_kwargs):
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::ffff:169.254.169.254", 0, 0, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    with pytest.raises(GatewayFailure) as excinfo:
        refuse_metadata_host("http://metadata.example/")
    assert excinfo.value.kind == "not_allowed"
