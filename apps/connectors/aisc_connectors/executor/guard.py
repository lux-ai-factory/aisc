"""Outbound safety for everything that leaves this service (spec D7)."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from aisc_connectors.executor.errors import GatewayFailure

_METADATA = [ipaddress.ip_network("169.254.0.0/16"), ipaddress.ip_network("fd00:ec2::254/128")]


def refuse_metadata_host(url: str) -> None:
    host = urlsplit(url).hostname
    if not host:
        raise GatewayFailure("invalid_input", f"{url!r} has no host")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror as exc:
        raise GatewayFailure("dns", f"{host} does not resolve") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if any(ip in net for net in _METADATA):
            raise GatewayFailure("not_allowed", f"{host} resolves to a link-local metadata address")
