"""The platform's client of the plugin publisher, the internal service that fetches a test's
lux-ai-factory repo, builds it and publishes it to this stack's package index.

Every call carries PLUGIN_PUBLISHER_TOKEN in the service-token header. No error raised here quotes
the token or the URL's credentials."""
from __future__ import annotations

import os
from urllib.parse import quote, urlsplit

import httpx

#: the header aisc_identity.service_tokens reads; not imported from there, because catalogue.py, which
#: uses this module, also runs on its own from scripts/start.sh where aisc_identity is not installed
SERVICE_TOKEN_HEADER = "X-AISC-Service-Token"

#: reading a source clones the repo; publishing builds it too, and may wait behind another build
SOURCE_TIMEOUT_S = 20
PUBLISH_TIMEOUT_S = 600


class PublisherError(RuntimeError):
    """The publisher could not be asked, or refused. The message says why, with no secret in it."""


def _base() -> str:
    url = (os.environ.get("PLUGIN_PUBLISHER_URL") or "").strip().rstrip("/")
    if not url:
        raise PublisherError("the plugin publisher is not configured (PLUGIN_PUBLISHER_URL is not set)")
    return url


def _shown(url: str) -> str:
    """The URL without its credentials, for a message."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.hostname}{f':{parts.port}' if parts.port else ''}"


def _headers() -> dict:
    token = os.environ.get("PLUGIN_PUBLISHER_TOKEN") or ""
    if not token:
        raise PublisherError("the plugin publisher is not configured (PLUGIN_PUBLISHER_TOKEN is not set)")
    return {SERVICE_TOKEN_HEADER: token}


def _detail(r: httpx.Response) -> str:
    try:
        found = r.json().get("detail")
    except (ValueError, AttributeError):
        found = None
    return str(found) if found else f"the plugin publisher answered {r.status_code}"


def _call(method: str, path: str, timeout: float, body: dict | None = None) -> httpx.Response:
    base = _base()
    headers = _headers()
    try:
        return httpx.request(method, f"{base}{path}", json=body, headers=headers, timeout=timeout)
    except httpx.TimeoutException:
        raise PublisherError(f"the plugin publisher at {_shown(base)} did not answer within {timeout:g} s") from None
    except httpx.HTTPError as exc:
        raise PublisherError(f"the plugin publisher at {_shown(base)} is not reachable "
                             f"({type(exc).__name__})") from None


UNREADABLE = "the plugin publisher answered something unreadable"


def _answer(r: httpx.Response) -> dict:
    """A 200's body, which must be a JSON object with a version in it."""
    try:
        body = r.json()
    except ValueError:
        raise PublisherError(UNREADABLE) from None
    if not isinstance(body, dict) or not isinstance(body.get("version"), str) or not body["version"]:
        raise PublisherError(UNREADABLE)
    return body


def source(repo: str) -> dict | None:
    """{"repo", "branch", "package", "version"} at the head of the repo; None when the publisher
    cannot read that repo (missing, no access, unreadable project)."""
    r = _call("GET", f"/sources/{quote(repo, safe='')}", SOURCE_TIMEOUT_S)
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise PublisherError(_detail(r))
    return _answer(r)


def publish(repo: str, package: str) -> dict:
    """Has that repo fetched, built and published unless the index holds its version already:
    {"package", "version", "published"}."""
    r = _call("POST", "/publish", PUBLISH_TIMEOUT_S, {"repo": repo, "package": package})
    if r.status_code != 200:
        raise PublisherError(_detail(r))
    return _answer(r)
