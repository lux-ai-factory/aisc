"""Downloading a spec: bounded in size and time, and never from a metadata address."""
from __future__ import annotations

import httpx

from aisc_connectors.executor.guard import refuse_metadata_host
from aisc_connectors.importers.errors import ImportFailed
from aisc_connectors.settings import settings


def fetch_text(url: str) -> str:
    refuse_metadata_host(url)
    limit = settings().max_spec_bytes
    try:
        with httpx.stream("GET", url, timeout=20, follow_redirects=True) as response:
            if response.status_code >= 400:
                raise ImportFailed(f"{url} answered {response.status_code}")
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > limit:
                    raise ImportFailed(f"the document is larger than {limit} bytes")
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise ImportFailed(f"could not download {url}: {exc}") from exc
    return b"".join(chunks).decode("utf-8", errors="replace")
