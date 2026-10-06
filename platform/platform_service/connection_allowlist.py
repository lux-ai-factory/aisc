"""Which internal hosts a project's connections may reach.

Public addresses need no entry. An internal one (loopback, private, link-local, ...) is refused
by the plugin-side guard (aisc_plugin_interface.connections.guard_url) unless it is allowed:
by the deployment's CONNECTIONS_ALLOWED_HOSTS (the floor, set by the operator and not editable
here) or by the project's own entries (connection.allowed_host, edited by its owners and
platform admins). Some addresses are never allowed from the UI: the stack's own services,
loopback (the platform itself) and cloud metadata. They are refused when an entry is saved and
again at every call, on the resolved address, so re-pointing an allowed name reaches none of
them. The floor may still allow them: that is the operator's explicit choice.

The rule of a project is computed at every call, so a change applies with no restart; the
platform hands it to the run in the resolve response, so the eval worker needs no copy.
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket

from platform_service import connection_store

#: Every name the stack's services answer to on its networks, in every compose file of the repo
#: (service, container and alias names), and localhost. scripts/tests/test_connections_stack.py
#: checks it against the compose files.
STACK_SERVICES = frozenset({
    "aisc-backend", "aisc-backend-migrate", "aisc-backend-standalone", "aisc-eval", "aisc-eval-flower",
    "aisc-eval-worker", "aisc-eval-worker-standalone", "aisc-webapp", "aisc-webapp-standalone",
    "backend", "caddy", "catalogue-private", "control-objectives", "control-objectives-migrate", "controls-migrate",
    "controls-pdf", "controls-web", "dashboard", "dashboard-migrate", "devpi", "devpi-standalone",
    "eval", "immudb", "immudb-key", "isolate", "keycloak", "ledger-pool", "make_buckets", "minio", "minio-standalone",
    "oauth2-proxy", "pgadmin", "platform", "plugin-downloader", "plugin-publisher", "postgres",
    "postgres-setup", "postgres-standalone", "qualification-agents", "qualification-llm",
    "qualification-migrate", "qualification-ontology", "qualification-pdf", "qualification-prefill",
    "qualification-web", "rabbitmq", "rabbitmq-standalone", "redis", "redis-standalone",
    "report-composer", "report-composer-migrate", "report-grants", "report-renderer", "schema-docs",
    "webapp", "localhost",
})
#: Cloud metadata endpoints (AWS, Azure, GCP, Oracle, DigitalOcean: 169.254.169.254; AWS ECS task
#: metadata: 169.254.170.2; AWS IPv6: fd00:ec2::254; Alibaba: 100.100.100.200).
METADATA_ADDRESSES = frozenset({"169.254.169.254", "169.254.170.2", "fd00:ec2::254", "100.100.100.200"})
METADATA_NAMES = frozenset({"metadata.google.internal", "metadata", "instance-data", "instance-data.ec2.internal"})

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOSTNAME = re.compile(rf"^{_LABEL}(?:\.{_LABEL})*$")


class InvalidEntry(ValueError):
    """Not a host or host:port."""


class DeniedEntry(ValueError):
    """A service of the stack, loopback or a metadata address: never allowed from the UI."""


def resolve(host: str) -> set[str]:
    """The addresses a name resolves to from the platform (inside the stack's networks); empty when
    it does not resolve. Replaced in the tests."""
    try:
        return {info[4][0] for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)}
    except (socket.gaierror, UnicodeError):
        return set()


def split(entry: str) -> tuple[str, int | None]:
    """(host, port) of an entry, lower case; InvalidEntry unless it is a host name, an IPv4 address or
    a bracketed IPv6 address, with an optional port."""
    text = entry.strip().lower()
    port = None
    if text.startswith("["):
        host, sep, rest = text[1:].partition("]")
        if not sep or (rest and not rest.startswith(":")):
            raise InvalidEntry("an IPv6 address goes in brackets: [fd00::5] or [fd00::5]:8500")
        port_text = rest[1:] if rest else None
    else:
        host, _, port_text = text.partition(":") if text.count(":") == 1 else (text, "", None)
        port_text = port_text or None
    if port_text is not None:
        if not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
            raise InvalidEntry("the port is a number from 1 to 65535")
        port = int(port_text)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if text.startswith("[") or len(host) > 253 or not _HOSTNAME.match(host):
            raise InvalidEntry("a host name, an IPv4 address or a bracketed IPv6 address, with an optional :port") from None
    return host, port


def normalise(entry: str) -> str:
    """The entry as stored and as the guard compares it: host or host:port, lower case."""
    host, port = split(entry)
    shown = f"[{host}]" if ":" in host else host
    return shown if port is None else f"{shown}:{port}"


def _guard_form(entry: str) -> str:
    """The form guard_url matches: its hostname has no brackets."""
    host, port = split(entry)
    return host if port is None else f"{host}:{port}"


def floor() -> list[str]:
    """The deployment's entries (CONNECTIONS_ALLOWED_HOSTS), as the operator wrote them."""
    return [h.strip().lower() for h in (os.environ.get("CONNECTIONS_ALLOWED_HOSTS") or "").split(",") if h.strip()]


def _is_loopback(ip: str) -> bool:
    return ipaddress.ip_address(ip).is_loopback


def denied_addresses() -> set[str]:
    """Every address a stack service resolves to, plus metadata; less the addresses of the floor's
    entries, which the operator allowed on purpose. Loopback is refused by name and by range in
    why_denied; here, only the addresses the guard compares resolved addresses with."""
    denied = set(METADATA_ADDRESSES)
    for name in STACK_SERVICES | METADATA_NAMES:
        denied |= resolve(name)
    exempt: set[str] = set()
    for entry in floor():
        try:
            host, _port = split(entry)
        except InvalidEntry:
            continue
        exempt |= {host} if _literal(host) else resolve(host)
    return {a for a in denied if a not in exempt and not _is_loopback(a)}


def _literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def why_denied(entry: str) -> str | None:
    """Why an entry can never be allowed from the UI, or None."""
    host, _port = split(entry)
    if host in STACK_SERVICES:
        return f"{host} is a service of this deployment: never allowed here"
    if host in METADATA_NAMES or host in METADATA_ADDRESSES:
        return f"{host} is a cloud metadata address: never allowed here"
    addresses = {host} if _literal(host) else resolve(host)
    if any(_is_loopback(a) for a in addresses):
        return f"{host} is loopback, the platform itself: never allowed here"
    if addresses & METADATA_ADDRESSES:
        return f"{host} resolves to a cloud metadata address: never allowed here"
    for name in sorted(STACK_SERVICES):
        if addresses & resolve(name):
            return f"{host} resolves to {name}, a service of this deployment: never allowed here"
    return None


def rule(pid) -> dict:
    """What a connection of this project may reach, now: the floor and the project's entries that
    are not denied, and the addresses never reachable (for the guard, at the call)."""
    allowed = [_guard_form(h) for h in floor() if _valid(h)]
    for row in entries(pid):
        if why_denied(row["host"]) is None and _guard_form(row["host"]) not in allowed:
            allowed.append(_guard_form(row["host"]))
    return {"allowed_hosts": allowed, "denied_addresses": sorted(denied_addresses())}


def _valid(entry: str) -> bool:
    try:
        split(entry)
        return True
    except InvalidEntry:
        return False


# the project's entries (connection.allowed_host)
def entries(pid) -> list[dict]:
    with connection_store.connect(pid) as conn:
        return conn.execute("SELECT host, note, updated_at, updated_by FROM connection.allowed_host"
                            " ORDER BY host").fetchall()


def put(pid, entry: str, note: str | None, subject: str) -> dict:
    """Add or update an entry; InvalidEntry or DeniedEntry, and nothing is written, when it may not be.
    The ledger's item is the entry as the route got it, so it matches the witnessed path."""
    from platform_service.ledger import outbox

    host = normalise(entry)
    reason = why_denied(host)
    if reason:
        raise DeniedEntry(reason)
    with connection_store.connect(pid) as conn, conn.transaction():
        old = conn.execute("SELECT note FROM connection.allowed_host WHERE host = %s", (host,)).fetchone()
        outbox.emit_project(conn, "allowlist.host.allowed", item_type="allowed_host", item_id=entry,
                            details={"note_before": old["note"] if old else None, "note_after": note})
        return conn.execute(
            "INSERT INTO connection.allowed_host (host, note, updated_by) VALUES (%s, %s, %s)"
            " ON CONFLICT (host) DO UPDATE SET note = EXCLUDED.note, updated_by = EXCLUDED.updated_by,"
            " updated_at = now() RETURNING host, note, updated_at, updated_by", (host, note, subject)).fetchone()


def remove(pid, entry: str) -> bool:
    from platform_service.ledger import outbox

    host = normalise(entry)
    with connection_store.connect(pid) as conn, conn.transaction():
        gone = conn.execute("DELETE FROM connection.allowed_host WHERE host = %s RETURNING host",
                            (host,)).fetchone() is not None
        if gone:
            outbox.emit_project(conn, "allowlist.host.removed", item_type="allowed_host", item_id=entry)
        return gone
