"""The ledger anchor a generated report prints (ledger phase 9, M3).

At generation the composer asks the platform for the project log's newest entry, as the person
generating it (their gateway token: members may read their project's log). The report prints the entry's
seq and digest; `report.generated`, written later in the same log, names the anchor and the document's
sha256, so a reader with the PDF and an export of the log checks both offline
(scripts/verify-ledger-export.py --anchor and --document).

Best effort: with the ledger off, or the platform not answering, the report prints no anchor and its
event says so (an anchor of null).
"""
from __future__ import annotations

import logging
import os
import re

import httpx

from . import ledger

_log = logging.getLogger(__name__)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
TIMEOUT_S = 3.0


def _token(request) -> str | None:
    token = request.headers.get("x-auth-request-access-token")
    if token:
        return token
    auth = request.headers.get("authorization") or ""
    return auth[7:] if auth.lower().startswith("bearer ") else None


def fetch(request, project: dict) -> dict | None:
    """{"seq", "entry_sha256"} of the project log's newest entry, or None."""
    if not ledger.on():
        return None
    token = _token(request)
    base = os.environ.get("PLATFORM_URL", "").rstrip("/")
    if not base or not token:
        return None
    try:
        with httpx.Client(timeout=TIMEOUT_S) as http:
            r = http.get(f"{base}/projects/{project['slug']}/ledger/head",
                         headers={"Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            return None
        head = r.json()
    except (httpx.HTTPError, ValueError):
        _log.warning("project %s: the ledger head could not be read; the report prints none", project["pid"])
        return None
    if not isinstance(head.get("seq"), int) or not _HEX64.match(str(head.get("entry_sha256") or "")):
        return None
    return {"seq": head["seq"], "entry_sha256": head["entry_sha256"]}
