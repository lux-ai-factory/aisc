"""Each project's connections to the systems it assesses, in the project's own database (schema
`connection`). Keys are Fernet tokens made with the same key list as the LLM keys
(llm_store.fernet), and rotated with them (`python -m platform_service.llm_store rotate`).

Only `descriptor` selects the ciphertext, and only the internal resolve route and the Test route
call it; nothing else ever reads it.
"""
from __future__ import annotations

import psycopg
from psycopg.types.json import Jsonb

from platform_service import llm_store

KEEP = llm_store.KEEP
#: every column a response may carry (never secret_ciphertext)
PUBLIC = ("name", "label", "kind", "base_url", "method", "path", "headers", "secret_header", "body_template",
          "response_path", "refusal", "model", "timeout_s", "protocol_version", "engine_component", "updated_at",
          "updated_by", "last_test_at", "last_test_ok", "last_test_detail")
_SELECT = ", ".join(PUBLIC) + ", secret_ciphertext IS NOT NULL AS has_secret"
_JSON = ("headers", "body_template", "refusal")


def connect(pid) -> psycopg.Connection:
    return llm_store.connect(pid)


def list_connections(pid) -> list[dict]:
    with connect(pid) as conn:
        return conn.execute(f"SELECT {_SELECT} FROM connection.endpoint WHERE deleted_at IS NULL"
                            " ORDER BY name").fetchall()


def get(pid, name: str, *, with_deleted: bool = False) -> dict | None:
    with connect(pid) as conn:
        return conn.execute(f"SELECT {_SELECT}, deleted_at FROM connection.endpoint WHERE name = %s"
                            + ("" if with_deleted else " AND deleted_at IS NULL"), (name,)).fetchone()


def save(pid, name: str, fields: dict, *, ciphertext=KEEP, subject: str | None) -> dict:
    """Insert, update or revive a connection; the key column follows KEEP / None / token."""
    values = {k: (Jsonb(v) if k in _JSON and v is not None else v) for k, v in fields.items()}
    cols = list(values)
    params = {**values, "name": name, "ciphertext": None if ciphertext is KEEP else ciphertext,
              "set_key": ciphertext is not KEEP, "subject": subject}
    insert_cols = ", ".join(["name", *cols, "secret_ciphertext", "updated_by"])
    insert_vals = ", ".join(["%(name)s", *[f"%({c})s" for c in cols], "%(ciphertext)s", "%(subject)s"])
    updates = ", ".join([f"{c} = EXCLUDED.{c}" for c in cols])
    with connect(pid) as conn:
        return conn.execute(
            f"INSERT INTO connection.endpoint ({insert_cols}) VALUES ({insert_vals})"
            f" ON CONFLICT (name) DO UPDATE SET {updates},"
            "  secret_ciphertext = CASE WHEN %(set_key)s THEN EXCLUDED.secret_ciphertext"
            "                      ELSE connection.endpoint.secret_ciphertext END,"
            "  updated_at = now(), updated_by = EXCLUDED.updated_by, deleted_at = NULL"
            f" RETURNING {_SELECT}", params).fetchone()


def set_engine_component(pid, name: str, component: str) -> None:
    with connect(pid) as conn:
        conn.execute("UPDATE connection.endpoint SET engine_component = %s WHERE name = %s", (component, name))


def delete(pid, name: str) -> bool:
    """Mark it deleted; the row stays for the evaluations that used it."""
    with connect(pid) as conn:
        return conn.execute("UPDATE connection.endpoint SET deleted_at = now() WHERE name = %s"
                            " AND deleted_at IS NULL RETURNING name", (name,)).fetchone() is not None


def record_test(pid, name: str, ok: bool, detail: str) -> None:
    with connect(pid) as conn:
        conn.execute("UPDATE connection.endpoint SET last_test_at = now(), last_test_ok = %s,"
                     " last_test_detail = %s WHERE name = %s", (ok, detail[:500], name))


def descriptor(pid, name: str) -> dict | None:
    """Everything, the key still encrypted (`secret_ciphertext`), plus `deleted_at`; or None."""
    with connect(pid) as conn:
        return conn.execute(f"SELECT {', '.join(PUBLIC)}, secret_ciphertext, deleted_at"
                            " FROM connection.endpoint WHERE name = %s", (name,)).fetchone()


def rotate(conn: psycopg.Connection, multi) -> tuple[int, int]:
    """(rotated, unreadable) for one project's connection keys, on an open connection."""
    if conn.execute("SELECT to_regclass('connection.endpoint')").fetchone()[0] is None:
        return 0, 0
    rotated = unreadable = 0
    for name, token in conn.execute("SELECT name, secret_ciphertext FROM connection.endpoint"
                                    " WHERE secret_ciphertext IS NOT NULL").fetchall():
        try:
            fresh = multi.rotate(token.encode()).decode()
        except llm_store.InvalidToken:
            unreadable += 1
            continue
        conn.execute("UPDATE connection.endpoint SET secret_ciphertext = %s WHERE name = %s", (fresh, name))
        rotated += 1
    return rotated, unreadable


# ── run keys ─────────────────────────────────────────────────────────────────

def issue_run_key(pid, name: str, key_hash: str, fingerprint: str, ttl_s: int):
    """Store a run key's hash; returns its expiry."""
    with connect(pid) as conn:
        return conn.execute("INSERT INTO connection.run_key (key_hash, name, fingerprint, expires_at)"
                            " VALUES (%s, %s, %s, now() + make_interval(secs => %s)) RETURNING expires_at",
                            (key_hash, name, fingerprint, ttl_s)).fetchone()["expires_at"]


def use_run_key(pid, name: str, key_hash: str) -> bool:
    """Count one use of a live key of this connection; False when it is not one."""
    with connect(pid) as conn:
        return conn.execute("UPDATE connection.run_key SET uses = uses + 1, last_used_at = now()"
                            " WHERE key_hash = %s AND name = %s AND expires_at > now() RETURNING key_hash",
                            (key_hash, name)).fetchone() is not None
