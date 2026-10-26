"""The allowlist's name lookups are kept for PLATFORM_ALLOWLIST_CACHE_S seconds per name (default 30, 0
turns the cache off), so a facade call does not resolve every service name of the stack each time. Past
its expiry a name is looked up again, so the cache never keeps a name allowed once it resolves to an
address that is refused. No database: the lookups are replaced at the socket."""
from __future__ import annotations

import socket
import time
import uuid

import pytest

from platform_service import connection_allowlist


class Lookups:
    """socket.getaddrinfo as the allowlist sees it: the addresses in `table`, else a failed lookup; every
    name asked is counted."""

    def __init__(self):
        self.table: dict[str, list[str]] = {}
        self.asked: list[str] = []

    def __call__(self, host, port, *args, **kwargs):
        self.asked.append(host)
        if host not in self.table:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 0)) for ip in self.table[host]]

    def count(self, host):
        return self.asked.count(host)


@pytest.fixture
def lookups(monkeypatch):
    fake = Lookups()
    monkeypatch.setattr(connection_allowlist.socket, "getaddrinfo", fake)
    monkeypatch.delenv("PLATFORM_ALLOWLIST_CACHE_S", raising=False)
    monkeypatch.delenv("CONNECTIONS_ALLOWED_HOSTS", raising=False)
    return fake


def unique_host() -> str:
    return f"system-{uuid.uuid4().hex[:12]}.example"


def test_a_second_rule_in_the_window_looks_up_no_name_again(lookups):
    connection_allowlist.denied_addresses()
    lookups.asked.clear()
    connection_allowlist.denied_addresses()
    assert lookups.asked == [], f"{len(lookups.asked)} names looked up again within the cache window"


def test_an_entry_and_the_stack_services_are_looked_up_once_in_the_window(lookups):
    host = unique_host()
    lookups.table[host] = ["203.0.113.7"]
    assert connection_allowlist.why_denied(host) is None
    lookups.asked.clear()
    assert connection_allowlist.why_denied(host) is None
    assert connection_allowlist.why_denied(host) is None
    assert lookups.asked == [], f"looked up again within the cache window: {sorted(set(lookups.asked))[:5]}"


def test_a_name_that_now_resolves_to_a_refused_address_is_refused_after_the_window(lookups, monkeypatch):
    monkeypatch.setenv("PLATFORM_ALLOWLIST_CACHE_S", "1")
    host = unique_host()
    lookups.table[host] = ["203.0.113.7"]
    assert connection_allowlist.why_denied(host) is None
    lookups.table[host] = ["169.254.169.254"]
    time.sleep(1.3)
    assert connection_allowlist.why_denied(host) == f"{host} resolves to a cloud metadata address: never allowed here"
    assert lookups.count(host) == 2


def test_with_the_cache_off_every_call_looks_up_again(lookups, monkeypatch):
    monkeypatch.setenv("PLATFORM_ALLOWLIST_CACHE_S", "0")
    host = unique_host()
    lookups.table[host] = ["203.0.113.7"]
    assert connection_allowlist.why_denied(host) is None
    lookups.table[host] = ["169.254.169.254"]
    assert connection_allowlist.why_denied(host) == f"{host} resolves to a cloud metadata address: never allowed here"
    assert lookups.count(host) == 2
    lookups.asked.clear()
    connection_allowlist.denied_addresses()
    connection_allowlist.denied_addresses()
    assert lookups.count("postgres") == 2


def test_with_the_cache_off_a_service_address_is_refused_at_once(lookups, monkeypatch):
    monkeypatch.setenv("PLATFORM_ALLOWLIST_CACHE_S", "0")
    lookups.table["postgres"] = ["10.9.8.7"]
    assert "10.9.8.7" in connection_allowlist.denied_addresses()
    lookups.table["postgres"] = ["10.9.8.6"]
    denied = connection_allowlist.denied_addresses()
    assert "10.9.8.6" in denied and "10.9.8.7" not in denied
