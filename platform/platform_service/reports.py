"""The reports of one AI card version, as the sandbox page shows them. The report composer keeps them in
tables no reader is granted, so it is asked with the caller's own token."""
from __future__ import annotations

import os

import httpx

from platform_service.targets import GATEWAY_TOKEN_HEADER

TIMEOUT_S = 10


class ComposerUnavailable(Exception):
    pass


def _base() -> str:
    return (os.environ.get("REPORT_COMPOSER_URL") or "http://report-composer:8095").rstrip("/")


def of_version(slug: str, version_pid: str, token: str) -> dict:
    """{"count", "latest"}: how many reports of the version finished, and the newest with its layout and
    its download path on the composer (None when there is none)."""
    try:
        r = httpx.get(f"{_base()}/api/p/{slug}/reports", params={"system_id": version_pid}, timeout=TIMEOUT_S,
                      headers={"Authorization": f"Bearer {token}", GATEWAY_TOKEN_HEADER: token})
    except httpx.HTTPError as exc:
        raise ComposerUnavailable(f"could not be reached ({type(exc).__name__})") from None
    if r.status_code != 200:
        raise ComposerUnavailable(f"answered {r.status_code}")
    return r.json()
