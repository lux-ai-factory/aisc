"""The witness (spec 3; I1, I2, I9, T5, T6, T18-T20, T23): Caddy's forward_auth asks it about every
write before the app sees it, and it records who made the request.

Caddy sends (06-spike.md G8): the gateway secret, the app the handle names (`X-AISC-App`), the
unstripped URI (`X-AISC-Original-Uri`), the method, the person's gateway token and, for a Next.js
server action, its `Next-Action` id. The witness trusts nothing else.

- `LEDGER_MODE=off`: nothing is witnessed (Caddy's snippet is empty anyway).
- Without the gateway secret: 401 and no record; with none configured: 503.
- `enforce`: a request with no verified person is refused (401, or a 302 to sign in for a page load);
  `record`: it passes, recorded as unverified with the reason.
- The record goes to Postgres (`ledger.witness`), never to immudb, so the request never waits on it.
"""
from __future__ import annotations

import hmac
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import quote, urlsplit

from platform_service.ledger import registry, secrets, settings

_FIELDS = ("request_id", "at", "mode", "app", "method", "route_path", "query_hmac", "host", "project_pid",
           "member", "actor_ref", "verified", "reason", "next_action", "token_jti", "token_exp")


@dataclass
class Answer:
    status: int
    headers: dict


def _header(headers, name: str) -> str:
    lowered = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lowered:
            return (value or "").strip()
    return ""


def mode() -> str:
    value = os.environ.get("LEDGER_MODE", "off").strip().lower()
    return value if value in ("off", "record", "enforce") else "off"


def _project(app: str, path: str, headers) -> str | None:
    """The pid the request is about, by the app's rule (registry.APP_PROJECT_RULES), if it exists."""
    from platform_service import db

    kind, rule = registry.APP_PROJECT_RULES.get(app, ("none", None))
    if kind in ("slug", "pid"):
        m = re.match(rule, path)
        identifier = m.group("project") if m else None
    elif kind == "header":
        identifier = _header(headers, rule) or None
    else:                                                            # "bridge" (phase 9) and "none"
        identifier = None
    if not identifier:
        return None
    try:
        project = db.get_project(identifier)
    except Exception:                                                # a malformed id is no project
        return None
    return str(project["pid"]) if project else None


def _identity(headers):
    """(identity, reason): the verified person, or None and why not."""
    from aisc_identity.gateway import GatewayRefused, gateway_identity
    from aisc_identity.service import key_for_jwks, settings as auth

    config = auth()
    try:
        who = gateway_identity(headers, issuer=config.issuer, key_for=key_for_jwks(config.jwks_url),
                               gateway_client=os.environ.get("AISC_GATEWAY_CLIENT_ID", "aisc-gateway"),
                               leeway=settings.LEEWAY.total_seconds())
        return who, None
    except GatewayRefused as exc:
        return None, exc.reason


def witness(headers) -> Answer:
    """What Caddy gets: 200 with X-AISC-Request-Id (it copies it upstream), or a refusal."""
    current = mode()
    if current == "off":
        return Answer(200, {})
    expected = os.environ.get("AISC_WITNESS_GATEWAY_SECRET", "")
    if not expected:
        return Answer(503, {})
    if not hmac.compare_digest(_header(headers, "X-AISC-Gateway").encode(), expected.encode()):
        return Answer(401, {})
    app = _header(headers, "X-AISC-App")
    original = _header(headers, "X-AISC-Original-Uri")
    if app not in registry.GATEWAY_APPS or not original.startswith("/"):
        return Answer(400, {})
    parts = urlsplit(original)
    path = parts.path
    method = (_header(headers, "X-Forwarded-Method") or "GET").upper()
    who, reason = _identity(headers)
    if who is None and current == "enforce":
        if _header(headers, "Sec-Fetch-Dest") == "document":
            return Answer(302, {"Location": "/oauth2/start?rd=" + quote(original, safe="/")})
        return Answer(401, {})
    pid, member = None, False
    if who is not None:
        from platform_service import db

        pid = _project(app, path, headers)
        if pid is not None:
            member = db.role_in_project(pid, who.subject) is not None
            if not member:
                pid = None                                           # a stranger's request: platform log (D11)
    elif current == "record":
        # record mode observes before enforcing: an unverified request keeps the project its path names,
        # as no member, so the events it caused land in that log marked unverified (spec 3.4, 4.2)
        pid = _project(app, path, headers)
    actor_ref = None
    if who is not None:
        from platform_service.ledger import actors

        actor_ref = actors.ref_for(pid, who.subject, who.username)
    record = {
        "mode": current, "app": app, "method": method, "route_path": path,
        "query_hmac": secrets.digest(pid, "query", parts.query) if parts.query else None,
        "host": _header(headers, "X-Forwarded-Host") or None, "project_pid": pid, "member": member,
        "actor_ref": actor_ref, "verified": who is not None, "reason": reason,
        "next_action": _header(headers, "Next-Action") or None,
        "token_jti": who.token_id if who else None,
        "token_exp": datetime.fromtimestamp(who.expires_at, timezone.utc) if who else None,
    }
    request_id = _insert(record)
    return Answer(200, {"X-AISC-Request-Id": request_id})


def _insert(record: dict) -> str:
    from platform_service import db

    columns = list(record)
    with db.pool().connection() as conn:
        row = conn.execute(
            f"INSERT INTO ledger.witness ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})"
            " RETURNING request_id::text AS request_id", [record[c] for c in columns]).fetchone()
    return row["request_id"]


def record(request_id: str):
    """The stored record of one request, or None. Never a subject or a name (I10)."""
    from platform_service import db

    try:
        with db.pool().connection() as conn:
            row = conn.execute(f"SELECT {', '.join(_FIELDS)} FROM ledger.witness WHERE request_id = %s",
                               (request_id,)).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    data = dict(row)
    data["request_id"] = str(data["request_id"])
    data["project_pid"] = str(data["project_pid"]) if data["project_pid"] else None
    return SimpleNamespace(**data)


def count(*, route_path: str) -> int:
    from platform_service import db

    with db.pool().connection() as conn:
        return conn.execute("SELECT count(*) AS n FROM ledger.witness WHERE route_path = %s",
                            (route_path,)).fetchone()["n"]
