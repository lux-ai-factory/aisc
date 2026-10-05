"""Downloading a spec: bounded in size and time, and never from a metadata address.

httpx's built-in redirect following only checks the *first* URL against the metadata guard;
a target that 302s to a link-local address would otherwise be fetched without a second check.
So redirects are followed by hand here: every hop, including the first, is re-checked before
it is requested, and the whole download (all hops and all chunks) is bounded by one wall-clock
deadline, not just the per-request timeout.
"""
from __future__ import annotations

import time
from urllib.parse import urljoin

import httpx

from aisc_connectors.executor.guard import refuse_metadata_host
from aisc_connectors.importers.errors import ImportFailed
from aisc_connectors.settings import settings

_MAX_REDIRECTS = 5
_DEADLINE_SECONDS = 30.0
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


def fetch_text(url: str) -> str:
    limit = settings().max_spec_bytes
    deadline = time.monotonic() + _DEADLINE_SECONDS
    current = url
    redirects = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ImportFailed(f"the download took longer than {int(_DEADLINE_SECONDS)} s")
        refuse_metadata_host(current)
        try:
            with httpx.stream(
                "GET", current, timeout=httpx.Timeout(min(20.0, remaining)), follow_redirects=False
            ) as response:
                if response.status_code in _REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location:
                        raise ImportFailed(f"{current} redirected without a Location header")
                    redirects += 1
                    if redirects > _MAX_REDIRECTS:
                        raise ImportFailed("too many redirects")
                    current = urljoin(current, location)
                    continue
                if response.status_code >= 400:
                    raise ImportFailed(f"{current} answered {response.status_code}")
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    if time.monotonic() > deadline:
                        raise ImportFailed(f"the download took longer than {int(_DEADLINE_SECONDS)} s")
                    size += len(chunk)
                    if size > limit:
                        raise ImportFailed(f"the document is larger than {limit} bytes")
                    chunks.append(chunk)
                return b"".join(chunks).decode("utf-8", errors="replace")
        except httpx.HTTPError as exc:
            raise ImportFailed(f"could not download {current}: {exc}") from exc
