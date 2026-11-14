"""Each project's LLM keys and model choices: a provider's key is a provider connection (`connection.endpoint`,
kind `provider`, named `llm-<provider>`) and an agent's choice is an agent use of it (`connection.use`), in the
project's own database (project-template/0030_connectivity.sql; the old schema `llm` is no longer written).

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
from urllib.parse import urlsplit

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
    "chart_assistant": "Chart assistant (Results dashboard)",
}
DEFAULT_OLLAMA_BASE_URL = "http://host.docker.internal:11434"


# environment, read on every call
def ollama_default() -> str:
    return os.environ.get("PLATFORM_OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL


def _host_port(url: str | None) -> str | None:
    """host:port of a URL, lower case, an IPv6 host in brackets; None when it has no host."""
    try:
        parts = urlsplit(url or "")
        host, port = (parts.hostname or "").lower(), parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return None
    if not host:
        return None
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def ollama_default_host() -> str | None:
    """host:port of ollama_default(), the local model server the operator set for every project."""
    return _host_port(ollama_default())


def operator_hosts(url: str | None) -> list[str]:
    """The operator's hosts a project's model address may use: the default local model server when `url` is on
    it (connection_allowlist.rule takes them as floor hosts), else none."""
    default = ollama_default_host()
    return [default] if default and _host_port(url) == default else []


# queries on one project's database
def connect(pid) -> psycopg.Connection:
    return projectdb.connect(pid)


def connection_name(provider: str) -> str:
    """The connection that holds a provider's key for the project's agents."""
    return f"llm-{provider}"


# A provider row, as the routes have always read it: its id, whether it has a key, its base URL (None when the
# connection keeps '', a hosted provider's catalogue URL) and when it changed.
_PROVIDER = ("SELECT provider, secret_ciphertext IS NOT NULL AS has_key, nullif(base_url, '') AS base_url, updated_at"
             " FROM connection.endpoint WHERE kind = 'provider' AND name = 'llm-' || provider AND deleted_at IS NULL")


def providers(pid) -> dict[str, dict]:
    """provider -> {"has_key", "base_url", "updated_at"}; never the ciphertext."""
    with connect(pid) as conn:
        rows = conn.execute(_PROVIDER).fetchall()
    return {r["provider"]: r for r in rows}


def ciphertext_of(pid, provider: str) -> str | None:
    with connect(pid) as conn:
        row = conn.execute("SELECT secret_ciphertext FROM connection.endpoint WHERE name = %s AND kind = 'provider'"
                           " AND deleted_at IS NULL", (connection_name(provider),)).fetchone()
    return row["secret_ciphertext"] if row else None


def _label(provider: str) -> str:
    from platform_service import llm_catalogue

    entry = llm_catalogue.PROVIDERS.get(provider)
    return entry.label if entry is not None else provider


def _upsert_provider(conn, provider: str, *, ciphertext=KEEP, base_url=KEEP, subject: str | None) -> dict:
    """The provider's connection for the agents (`llm-<provider>`), as the llm routes read it."""
    from platform_service.connection_store import upsert_provider

    upsert_provider(conn, connection_name(provider), label=_label(provider), provider=provider,
                    ciphertext=ciphertext, base_url=base_url, subject=subject)
    return conn.execute(_PROVIDER + " AND provider = %s", (provider,)).fetchone()


def save_provider(pid, provider: str, *, ciphertext=KEEP, base_url=KEEP, subject: str | None,
                  key_fingerprint: str | None = None) -> dict:
    """Insert or update a provider's connection; a KEEP column keeps its stored value."""
    from platform_service.ledger import outbox
    with connect(pid) as conn, conn.transaction():
        details = {"key": key_fingerprint} if key_fingerprint else {}
        if base_url is not KEEP:
            old = conn.execute(_PROVIDER + " AND provider = %s", (provider,)).fetchone()
            details["base_url_before"] = logged_url(pid, old["base_url"] if old else None)
            details["base_url_after"] = logged_url(pid, base_url)
        outbox.emit_project(conn, "llm.provider.saved", item_type="llm_provider", item_id=provider, details=details)
        return _upsert_provider(conn, provider, ciphertext=ciphertext, base_url=base_url, subject=subject)


def delete_provider(pid, provider: str) -> list[str] | bool:
    """The systems that use it (nothing deleted), else whether a provider was deleted (its key dropped)."""
    with connect(pid) as conn, conn.transaction():
        users = [r["agent"] for r in conn.execute(
            "SELECT agent FROM connection.use WHERE use = 'agent' AND connection = %s AND deleted_at IS NULL"
            " ORDER BY agent", (connection_name(provider),)).fetchall()]
        if users:
            return users
        gone = conn.execute("UPDATE connection.endpoint SET deleted_at = now(), secret_ciphertext = NULL"
                            " WHERE name = %s AND kind = 'provider' AND deleted_at IS NULL RETURNING name",
                            (connection_name(provider),)).fetchone()
        if gone is not None:
            from platform_service.ledger import outbox
            outbox.emit_project(conn, "llm.provider.removed", item_type="llm_provider", item_id=provider)
        return gone is not None


# An agent's live choice: its use row and the provider connection it runs on.
_CHOICE = ("FROM connection.use u JOIN connection.endpoint e ON e.name = u.connection"
           " WHERE u.use = 'agent' AND u.deleted_at IS NULL AND e.deleted_at IS NULL")


def choices(pid) -> dict[str, dict]:
    """system -> {"provider", "model"}"""
    with connect(pid) as conn:
        rows = conn.execute(f"SELECT u.agent, e.provider, u.model {_CHOICE}").fetchall()
    return {r["agent"]: {"provider": r["provider"], "model": r["model"]} for r in rows}


def provider_listing(pid, name: str) -> dict | None:
    """{"provider", "base_url", "ciphertext"} of a live provider connection, to list its models with its own address
    and key (Manage > Connectivity); None when there is no such provider connection. The ciphertext never leaves the
    route that decrypts it."""
    with connect(pid) as conn:
        row = conn.execute("SELECT provider, base_url, secret_ciphertext FROM connection.endpoint"
                           " WHERE name = %s AND kind = 'provider' AND deleted_at IS NULL", (name,)).fetchone()
    if row is None:
        return None
    return {"provider": row["provider"], "base_url": row["base_url"] or None, "ciphertext": row["secret_ciphertext"]}


def save_choice(pid, system: str, provider: str, model: str, *, subject: str | None,
                keyless_row: bool) -> None:
    from platform_service.ledger import outbox
    with connect(pid) as conn, conn.transaction():
        old = conn.execute(f"SELECT e.provider, u.model {_CHOICE} AND u.agent = %s", (system,)).fetchone()
        outbox.emit_project(conn, "llm.choice.saved", item_type="llm_choice", item_id=system,
                            details={"provider_before": old["provider"] if old else None, "provider_after": provider,
                                     "model_before": old["model"] if old else None, "model_after": model})
        if keyless_row and conn.execute(_PROVIDER + " AND provider = %s", (provider,)).fetchone() is None:
            _upsert_provider(conn, provider, subject=subject)
        _use_for_agent(conn, system, connection_name(provider), model, subject)


def _use_for_agent(conn, system: str, connection: str, model: str, subject: str | None) -> None:
    """The agent's one live use: moved to `connection` with `model`, or made."""
    live = conn.execute("SELECT 1 FROM connection.endpoint WHERE name = %s AND kind = 'provider'"
                        " AND deleted_at IS NULL", (connection,)).fetchone()
    if live is None:
        raise LookupError(f"no provider connection {connection!r} in this project")
    updated = conn.execute(
        "UPDATE connection.use SET connection = %s, model = %s, updated_at = now(), updated_by = %s"
        " WHERE use = 'agent' AND agent = %s AND deleted_at IS NULL RETURNING id",
        (connection, model, subject, system)).fetchone()
    if updated is None:
        conn.execute("INSERT INTO connection.use (connection, use, agent, model, updated_by)"
                     " VALUES (%s, 'agent', %s, %s, %s)", (connection, system, model, subject))


def save_agent(pid, system: str, connection: str, model: str, *, subject: str | None) -> None:
    """Run agent `system` on provider connection `connection` with `model` (Manage > Connectivity)."""
    from platform_service.ledger import outbox
    with connect(pid) as conn, conn.transaction():
        outbox.emit_project(conn, "connection.use.saved", item_type="connection_use", item_id=system,
                            details={"use": "agent", "connection": connection, "model": model})
        _use_for_agent(conn, system, connection, model, subject)


def remove_agent(pid, system: str) -> bool:
    """The agent goes back to the stack's own setting (Manage > Connectivity); False when it had no choice."""
    from platform_service.ledger import outbox
    with connect(pid) as conn, conn.transaction():
        gone = conn.execute("UPDATE connection.use SET deleted_at = now() WHERE use = 'agent' AND agent = %s"
                            " AND deleted_at IS NULL RETURNING id", (system,)).fetchone() is not None
        if gone:
            outbox.emit_project(conn, "connection.use.removed", item_type="connection_use", item_id=system,
                                details={"use": "agent"})
        return gone


def choice_connections(pid) -> dict[str, dict]:
    """system -> {"connection", "model"}, the agents' live choices by connection."""
    with connect(pid) as conn:
        rows = conn.execute(f"SELECT u.agent, u.connection, u.model {_CHOICE}").fetchall()
    return {r["agent"]: {"connection": r["connection"], "model": r["model"]} for r in rows}


def delete_choice(pid, system: str) -> bool:
    from platform_service.ledger import outbox
    with connect(pid) as conn, conn.transaction():
        gone = conn.execute("UPDATE connection.use SET deleted_at = now() WHERE use = 'agent' AND agent = %s"
                            " AND deleted_at IS NULL RETURNING id", (system,)).fetchone() is not None
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
            "SELECT e.provider, u.model, e.secret_ciphertext AS ciphertext, nullif(e.base_url, '') AS base_url"
            f" {_CHOICE} AND u.agent = %s", (system,)).fetchone()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
