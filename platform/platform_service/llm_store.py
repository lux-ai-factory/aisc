"""Each project's LLM keys and model choices, in the project's own database (schema `llm`).

A key is encrypted (secret_box, with PLATFORM_SECRETS_KEY) before it is written and is only decrypted for
the internal resolve route.

Rotation, from `platform/`:

    python -m platform_service.llm_store rotate

re-encrypts every stored key of every project under the newest key and prints counts only
(secret_box.rotate_all). Then, once it exits 0, the old key can be removed from PLATFORM_SECRETS_KEY.

This module never selects the ciphertext into anything that reaches a response:
only `ciphertext_of` and `resolve_choice` read it, and only the routes that decrypt
call them.
"""
from __future__ import annotations

import os
import sys

import psycopg

from platform_service import projectdb
# the crypto and rotation live in secret_box; these names are what the routes and stores call
from platform_service.secret_box import (KEEP, InvalidToken, KeyUnreadable, SecretsKeyError,  # noqa: F401
                                         fernet, main, rotate_all)
from platform_service.secret_box import open as decrypt, seal as encrypt  # noqa: F401

#: The agentic systems that can have a choice, in the order the page shows them.
SYSTEMS: dict[str, str] = {
    "card_agent": "Card agent (Qualification)",
    "risk_mapper": "Risk mapper (Control objectives)",
}
DEFAULT_OLLAMA_BASE_URL = "http://host.docker.internal:11434"


# environment, read on every call
def ollama_default() -> str:
    return os.environ.get("PLATFORM_OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL


# queries on one project's database
def connect(pid) -> psycopg.Connection:
    return projectdb.connect(pid)


def providers(pid) -> dict[str, dict]:
    """provider -> {"has_key", "base_url", "updated_at"}; never the ciphertext."""
    with connect(pid) as conn:
        rows = conn.execute(
            "SELECT provider, ciphertext IS NOT NULL AS has_key, base_url, updated_at"
            " FROM llm.provider").fetchall()
    return {r["provider"]: r for r in rows}


def ciphertext_of(pid, provider: str) -> str | None:
    with connect(pid) as conn:
        row = conn.execute("SELECT ciphertext FROM llm.provider WHERE provider = %s",
                           (provider,)).fetchone()
    return row["ciphertext"] if row else None


def save_provider(pid, provider: str, *, ciphertext=KEEP, base_url=KEEP, subject: str | None,
                  key_fingerprint: str | None = None) -> dict:
    """Insert or update a provider row; a KEEP column keeps its stored value."""
    params = {
        "provider": provider,
        "ciphertext": None if ciphertext is KEEP else ciphertext,
        "base_url": None if base_url is KEEP else base_url,
        "set_key": ciphertext is not KEEP,
        "set_url": base_url is not KEEP,
        "subject": subject,
    }
    from platform_service.ledger import outbox

    with connect(pid) as conn, conn.transaction():
        details = {"key": key_fingerprint} if key_fingerprint else {}
        if base_url is not KEEP:
            old = conn.execute("SELECT base_url FROM llm.provider WHERE provider = %s", (provider,)).fetchone()
            details["base_url_before"] = logged_url(pid, old["base_url"] if old else None)
            details["base_url_after"] = logged_url(pid, base_url)
        outbox.emit_project(conn, "llm.provider.saved", item_type="llm_provider", item_id=provider, details=details)
        return conn.execute(
            "INSERT INTO llm.provider (provider, ciphertext, base_url, updated_by)"
            " VALUES (%(provider)s, %(ciphertext)s, %(base_url)s, %(subject)s)"
            " ON CONFLICT (provider) DO UPDATE SET"
            "  ciphertext = CASE WHEN %(set_key)s THEN EXCLUDED.ciphertext ELSE llm.provider.ciphertext END,"
            "  base_url = CASE WHEN %(set_url)s THEN EXCLUDED.base_url ELSE llm.provider.base_url END,"
            "  updated_at = now(), updated_by = EXCLUDED.updated_by"
            " RETURNING provider, ciphertext IS NOT NULL AS has_key, base_url, updated_at",
            params).fetchone()


def delete_provider(pid, provider: str) -> list[str] | bool:
    """The systems that use it (nothing deleted), else whether a row was deleted."""
    with connect(pid) as conn, conn.transaction():
        users = [r["system"] for r in conn.execute(
            "SELECT system FROM llm.system_choice WHERE provider = %s ORDER BY system",
            (provider,)).fetchall()]
        if users:
            return users
        gone = conn.execute("DELETE FROM llm.provider WHERE provider = %s RETURNING provider",
                            (provider,)).fetchone()
        if gone is not None:
            from platform_service.ledger import outbox

            outbox.emit_project(conn, "llm.provider.removed", item_type="llm_provider", item_id=provider)
        return gone is not None


def choices(pid) -> dict[str, dict]:
    """system -> {"provider", "model"}"""
    with connect(pid) as conn:
        rows = conn.execute("SELECT system, provider, model FROM llm.system_choice").fetchall()
    return {r["system"]: {"provider": r["provider"], "model": r["model"]} for r in rows}


def save_choice(pid, system: str, provider: str, model: str, *, subject: str | None,
                keyless_row: bool) -> None:
    from platform_service.ledger import outbox

    with connect(pid) as conn, conn.transaction():
        old = conn.execute("SELECT provider, model FROM llm.system_choice WHERE system = %s", (system,)).fetchone()
        outbox.emit_project(conn, "llm.choice.saved", item_type="llm_choice", item_id=system,
                            details={"provider_before": old["provider"] if old else None, "provider_after": provider,
                                     "model_before": old["model"] if old else None, "model_after": model})
        if keyless_row:
            conn.execute("INSERT INTO llm.provider (provider, updated_by) VALUES (%s, %s)"
                         " ON CONFLICT (provider) DO NOTHING", (provider, subject))
        conn.execute(
            "INSERT INTO llm.system_choice (system, provider, model, updated_by)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (system) DO UPDATE SET provider = EXCLUDED.provider,"
            "  model = EXCLUDED.model, updated_at = now(), updated_by = EXCLUDED.updated_by",
            (system, provider, model, subject))


def delete_choice(pid, system: str) -> bool:
    from platform_service.ledger import outbox

    with connect(pid) as conn, conn.transaction():
        gone = conn.execute("DELETE FROM llm.system_choice WHERE system = %s RETURNING system",
                            (system,)).fetchone() is not None
        if gone:
            outbox.emit_project(conn, "llm.choice.removed", item_type="llm_choice", item_id=system)
        return gone


def logged_url(pid, url: str | None) -> str | None:
    """A base URL as the ledger keeps it: scheme, host and path; a user part or a
    query (an OpenAI-compatible URL can carry `?api-key=...`) only as its fingerprint."""
    if not url:
        return url
    from urllib.parse import urlsplit, urlunsplit

    from platform_service.ledger import secrets

    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    hidden = "".join(x for x in (parts.username or "", parts.password or "", parts.query, parts.fragment) if x)
    tail = f"#{secrets.fingerprint(pid, hidden)}" if hidden else ""
    return urlunsplit((parts.scheme, host, parts.path, "", "")) + tail


def resolve_choice(pid, system: str) -> dict | None:
    """{"provider", "model", "ciphertext", "base_url"} of the system's choice, or None."""
    with connect(pid) as conn:
        return conn.execute(
            "SELECT c.provider, c.model, p.ciphertext, p.base_url"
            " FROM llm.system_choice c JOIN llm.provider p USING (provider)"
            " WHERE c.system = %s", (system,)).fetchone()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
