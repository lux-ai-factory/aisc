"""Each project's LLM keys and model choices, in the project's own database (schema `llm`).

A key is encrypted with Fernet before it is written and is only decrypted for the
internal resolve route. `PLATFORM_SECRETS_KEY` is a comma list of Fernet keys, newest
first (the connectors vault pattern): the newest encrypts, any of them decrypts.

Rotation, from `platform/`:

    python -m platform_service.llm_store rotate

re-encrypts every stored key of every project under the newest key and prints counts
only. Then the old key can be removed from PLATFORM_SECRETS_KEY.

This module never selects the ciphertext into anything that reaches a response:
only `ciphertext_of` and `resolve_choice` read it, and only the routes that decrypt
call them.
"""
from __future__ import annotations

import os
import sys

import psycopg
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from platform_service import db, projectdb

#: The agentic systems that can have a choice, in the order the page shows them.
SYSTEMS: dict[str, str] = {
    "card_agent": "Card agent (Qualification)",
    "risk_mapper": "Risk mapper (Control objectives)",
}
DEFAULT_OLLAMA_BASE_URL = "http://host.docker.internal:11434"

#: "leave this column as it is", for save_provider
KEEP = object()


class SecretsKeyError(RuntimeError):
    """PLATFORM_SECRETS_KEY is missing or malformed; str() is the 503 detail."""


class KeyUnreadable(RuntimeError):
    """No configured Fernet key decrypts the stored key."""

    def __init__(self, provider: str):
        super().__init__(f"the stored key for {provider} cannot be decrypted; enter it again")


# ── environment, read on every call ──────────────────────────────────────────


def ollama_default() -> str:
    return os.environ.get("PLATFORM_OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL


def fernet() -> MultiFernet:
    raw = (os.environ.get("PLATFORM_SECRETS_KEY") or "").strip()
    if not raw:
        raise SecretsKeyError("PLATFORM_SECRETS_KEY is not set")
    keys = [part.strip() for part in raw.split(",") if part.strip()]
    try:
        return MultiFernet([Fernet(k) for k in keys])
    except (ValueError, TypeError):
        raise SecretsKeyError("PLATFORM_SECRETS_KEY is not a list of Fernet keys") from None


def encrypt(plaintext: str) -> str:
    return fernet().encrypt(plaintext.encode()).decode()


def decrypt(provider: str, token: str) -> str:
    multi = fernet()
    try:
        return multi.decrypt(token.encode()).decode()
    except InvalidToken:
        raise KeyUnreadable(provider) from None


# ── queries on one project's database ────────────────────────────────────────


def connect(pid) -> psycopg.Connection:
    return psycopg.connect(make_conninfo(db.dsn(), dbname=projectdb.database_name(pid)),
                           row_factory=dict_row)


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


def save_provider(pid, provider: str, *, ciphertext=KEEP, base_url=KEEP, subject: str | None) -> dict:
    """Insert or update a provider row; a KEEP column keeps its stored value."""
    params = {
        "provider": provider,
        "ciphertext": None if ciphertext is KEEP else ciphertext,
        "base_url": None if base_url is KEEP else base_url,
        "set_key": ciphertext is not KEEP,
        "set_url": base_url is not KEEP,
        "subject": subject,
    }
    with connect(pid) as conn:
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
        return gone is not None


def choices(pid) -> dict[str, dict]:
    """system -> {"provider", "model"}"""
    with connect(pid) as conn:
        rows = conn.execute("SELECT system, provider, model FROM llm.system_choice").fetchall()
    return {r["system"]: {"provider": r["provider"], "model": r["model"]} for r in rows}


def save_choice(pid, system: str, provider: str, model: str, *, subject: str | None,
                keyless_row: bool) -> None:
    with connect(pid) as conn, conn.transaction():
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
    with connect(pid) as conn:
        return conn.execute("DELETE FROM llm.system_choice WHERE system = %s RETURNING system",
                            (system,)).fetchone() is not None


def resolve_choice(pid, system: str) -> dict | None:
    """{"provider", "model", "ciphertext", "base_url"} of the system's choice, or None."""
    with connect(pid) as conn:
        return conn.execute(
            "SELECT c.provider, c.model, p.ciphertext, p.base_url"
            " FROM llm.system_choice c JOIN llm.provider p USING (provider)"
            " WHERE c.system = %s", (system,)).fetchone()


# ── rotation ─────────────────────────────────────────────────────────────────


def rotate_all(base_dsn: str) -> dict[str, int]:
    """Re-encrypt every stored key of every project under the newest Fernet key.

    Never aborts: a project that cannot be reached, one without the llm tables and a
    key no configured Fernet key decrypts are counted and skipped."""
    multi = fernet()
    counts = {"rotated": 0, "projects": 0, "unreadable": 0, "without_llm": 0, "unreachable": 0}
    # a plain connection, not db.pool(): the pool would migrate and provision
    with psycopg.connect(base_dsn) as conn:
        pids = [r[0] for r in conn.execute("SELECT pid FROM core.project ORDER BY created_at").fetchall()]
    for pid in pids:
        try:
            conn = psycopg.connect(make_conninfo(base_dsn, dbname=projectdb.database_name(pid)))
        except psycopg.Error:
            counts["unreachable"] += 1
            continue
        with conn:
            # the connection keys (Manage → Connections) are made with the same key list
            from platform_service import connection_store
            rotated_here, unreadable = connection_store.rotate(conn, multi)
            counts["unreadable"] += unreadable
            if conn.execute("SELECT to_regclass('llm.provider')").fetchone()[0] is None:
                counts["without_llm"] += 1
                conn.commit()
                counts["rotated"] += rotated_here
                counts["projects"] += bool(rotated_here)
                continue
            rows = conn.execute("SELECT provider, ciphertext FROM llm.provider"
                                " WHERE ciphertext IS NOT NULL").fetchall()
            for provider, token in rows:
                try:
                    fresh = multi.rotate(token.encode()).decode()
                except InvalidToken:
                    counts["unreadable"] += 1
                    continue
                conn.execute("UPDATE llm.provider SET ciphertext = %s WHERE provider = %s",
                             (fresh, provider))
                rotated_here += 1
            conn.commit()
        counts["rotated"] += rotated_here
        if rotated_here:
            counts["projects"] += 1
    return counts


def main(argv: list[str]) -> int:
    if argv != ["rotate"]:
        print("usage: python -m platform_service.llm_store rotate", file=sys.stderr)
        return 2
    try:
        fernet()
    except SecretsKeyError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    c = rotate_all(db.dsn())
    print(f"rotated {c['rotated']} keys in {c['projects']} projects ({c['unreadable']} unreadable,"
          f" {c['without_llm']} without llm tables, {c['unreachable']} unreachable)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
