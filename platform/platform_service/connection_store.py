"""Each project's connections to the systems it assesses, in the project's own database (schema
`connection`). Two columns hold ciphertext: `secret_ciphertext` (the key) and `secret_headers_ciphertext`
(the secret headers, one token of a JSON object {name: value}; their names are public, in
`secret_header_names`). Both are Fernet tokens made with the same key list as the LLM keys
(llm_store.fernet), and rotated with them (`python -m platform_service.llm_store rotate`).

Only `descriptor` selects the ciphertext. Only routes/connections.call_descriptor_of decrypts it, for the
protocol doors and the Test button, to call the system; the resolve route answers without it.
"""
from __future__ import annotations

import psycopg
from psycopg.types.json import Jsonb

from platform_service import llm_store

KEEP = llm_store.KEEP
#: every column a response may carry (never secret_ciphertext nor secret_headers_ciphertext)
PUBLIC = ("name", "label", "kind", "base_url", "method", "path", "headers", "secret_header", "body_template",
          "response_path", "refusal", "model", "timeout_s", "protocol_version", "engine_component", "updated_at",
          "updated_by", "last_test_at", "last_test_ok", "last_test_detail", "target_key", "secret_header_names")
_SELECT = ", ".join(PUBLIC) + ", secret_ciphertext IS NOT NULL AS has_secret"
_JSON = ("headers", "body_template", "refusal", "secret_header_names")


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


class TargetSetOnce(ValueError):
    """The connection is already the endpoint of another target: nothing was written."""


def save(pid, name: str, fields: dict, *, ciphertext=KEEP, header_ciphertext=KEEP, subject: str | None) -> dict:
    """Insert, update or revive a connection; the key column follows KEEP / None / token, and so does
    the secret headers' column (`header_ciphertext`, with their names in fields["secret_header_names"]).

    A connection's target is set once: an update naming another target writes nothing and raises
    TargetSetOnce. The rule is in the upsert itself, so a save that read "no target yet" before
    another save set one cannot move it."""
    values = {k: (Jsonb(v) if k in _JSON and v is not None else v) for k, v in fields.items()}
    cols = list(values)
    params = {**values, "name": name, "ciphertext": None if ciphertext is KEEP else ciphertext,
              "set_key": ciphertext is not KEEP, "subject": subject,
              "header_ciphertext": None if header_ciphertext is KEEP else header_ciphertext,
              "set_headers": header_ciphertext is not KEEP}
    insert_cols = ", ".join(["name", *cols, "secret_ciphertext", "secret_headers_ciphertext", "updated_by"])
    insert_vals = ", ".join(["%(name)s", *[f"%({c})s" for c in cols], "%(ciphertext)s", "%(header_ciphertext)s",
                             "%(subject)s"])
    updates = ", ".join([f"{c} = EXCLUDED.{c}" for c in cols])
    from platform_service.ledger import outbox

    with connect(pid) as conn, conn.transaction():
        before = conn.execute(f"SELECT {_SELECT}, deleted_at FROM connection.endpoint WHERE name = %s",
                              (name,)).fetchone()
        changed = sorted("secret_headers" if c == "secret_header_names" else c
                         for c in fields if before is None or before.get(c) != fields[c]
                         or before.get("deleted_at") is not None)
        if header_ciphertext is not KEEP and "secret_headers" not in changed:
            changed = sorted([*changed, "secret_headers"])           # a value changed, the names did not
        outbox.emit_project(conn, "connection.saved", item_type="connection", item_id=name,
                            details={"changed": changed,
                                     "secret": "kept" if ciphertext is KEEP else ("removed" if ciphertext is None else "set")})
        once = (" WHERE connection.endpoint.target_key IS NULL"
                " OR connection.endpoint.target_key IS NOT DISTINCT FROM EXCLUDED.target_key"
                if "target_key" in fields else "")
        row = conn.execute(
            f"INSERT INTO connection.endpoint ({insert_cols}) VALUES ({insert_vals})"
            f" ON CONFLICT (name) DO UPDATE SET {updates},"
            "  secret_ciphertext = CASE WHEN %(set_key)s THEN EXCLUDED.secret_ciphertext"
            "                      ELSE connection.endpoint.secret_ciphertext END,"
            "  secret_headers_ciphertext = CASE WHEN %(set_headers)s THEN EXCLUDED.secret_headers_ciphertext"
            "                              ELSE connection.endpoint.secret_headers_ciphertext END,"
            "  updated_at = now(), updated_by = EXCLUDED.updated_by, deleted_at = NULL"
            f"{once} RETURNING {_SELECT}", params).fetchone()
        if row is None:                                   # rolls back the event emitted above
            raise TargetSetOnce(name)
        return row


def holder_of(pid, target_key: str) -> str | None:
    """The connection in use that is the endpoint of this target, if any."""
    with connect(pid) as conn:
        row = conn.execute("SELECT name FROM connection.endpoint WHERE target_key = %s AND deleted_at IS NULL",
                           (target_key,)).fetchone()
    return row["name"] if row else None


def endpoints_by_target(pid) -> dict[str, dict]:
    with connect(pid) as conn:
        rows = conn.execute("SELECT target_key, name, label, kind FROM connection.endpoint"
                            " WHERE target_key IS NOT NULL AND deleted_at IS NULL").fetchall()
    return {r["target_key"]: {"name": r["name"], "label": r["label"], "kind": r["kind"]} for r in rows}


def delete(pid, name: str) -> bool:
    """Mark it deleted; the row stays for the evaluations that used it."""
    from platform_service.ledger import outbox

    with connect(pid) as conn, conn.transaction():
        gone = conn.execute("UPDATE connection.endpoint SET deleted_at = now() WHERE name = %s"
                            " AND deleted_at IS NULL RETURNING name", (name,)).fetchone() is not None
        if gone:
            outbox.emit_project(conn, "connection.deleted", item_type="connection", item_id=name)
        return gone


def record_link(pid, name: str, retired: bool) -> None:
    """The link route changes the engine's side only; its event says whether a component was retired."""
    from platform_service.ledger import outbox

    with connect(pid) as conn, conn.transaction():
        outbox.emit_project(conn, "connection.saved", item_type="connection", item_id=name,
                            details={"changed": ["engine_component"] if retired else [], "secret": "kept"})


def record_test(pid, name: str, ok: bool, detail: str, result: str | None = None) -> None:
    """The probe's outcome; the ledger keeps only `result` (ok, refused, or the error's code), never the
    answer or the error text, which can quote the system under test."""
    from platform_service.ledger import outbox

    with connect(pid) as conn, conn.transaction():
        outbox.emit_project(conn, "connection.tested", item_type="connection", item_id=name,
                            details={"result": result or ("ok" if ok else "error")})
        conn.execute("UPDATE connection.endpoint SET last_test_at = now(), last_test_ok = %s,"
                     " last_test_detail = %s WHERE name = %s", (ok, detail[:500], name))


def descriptor(pid, name: str, conn=None) -> dict | None:
    """Everything, the key and the secret headers still encrypted (`secret_ciphertext`,
    `secret_headers_ciphertext`), plus `deleted_at`; or None."""
    with _on(pid, conn) as conn:
        return conn.execute(f"SELECT {', '.join(PUBLIC)}, secret_ciphertext, secret_headers_ciphertext, deleted_at"
                            " FROM connection.endpoint WHERE name = %s", (name,)).fetchone()


def rotate(conn: psycopg.Connection, multi) -> tuple[int, int, int]:
    """(rotated, unreadable, changed_meanwhile) for one project's connection keys and secret header sets,
    on an open connection; each column of each connection counts once.

    A token saved after the read is written only if it is still the one read: one saved meanwhile was
    made under the newest key already and is left as it is (counted as changed meanwhile)."""
    if conn.execute("SELECT to_regclass('connection.endpoint')").fetchone()[0] is None:
        return 0, 0, 0
    columns = ["secret_ciphertext"]
    if conn.execute("SELECT 1 FROM information_schema.columns WHERE table_schema = 'connection'"
                    " AND table_name = 'endpoint' AND column_name = 'secret_headers_ciphertext'").fetchone():
        columns.append("secret_headers_ciphertext")
    rotated = unreadable = meanwhile = 0
    for column in columns:
        for name, token in conn.execute(f"SELECT name, {column} FROM connection.endpoint"
                                        f" WHERE {column} IS NOT NULL").fetchall():
            try:
                fresh = multi.rotate(token.encode()).decode()
            except llm_store.InvalidToken:
                unreadable += 1
                continue
            if conn.execute(f"UPDATE connection.endpoint SET {column} = %s"
                            f" WHERE name = %s AND {column} = %s", (fresh, name, token)).rowcount:
                rotated += 1
            else:
                meanwhile += 1
    return rotated, unreadable, meanwhile


# run keys
def issue_run_key(pid, name: str, key_hash: str, fingerprint: str, ttl_s: int, pass_hash: str | None = None,
                  not_after=None):
    """Store a run key's hash, and the hash of the pass it was issued under (None: the connections token);
    returns its expiry, `ttl_s` from now or `not_after` (the pass's expiry) when that is sooner."""
    with connect(pid) as conn:
        return conn.execute("INSERT INTO connection.run_key (key_hash, name, fingerprint, expires_at, pass_hash)"
                            " VALUES (%s, %s, %s, least(now() + make_interval(secs => %s), %s::timestamptz), %s)"
                            " RETURNING expires_at",
                            (key_hash, name, fingerprint, ttl_s, not_after, pass_hash)).fetchone()["expires_at"]


def _on(pid, conn):
    """`conn` when the caller holds one open on the project's database (and closes it), else a new one."""
    from contextlib import nullcontext
    return nullcontext(conn) if conn is not None else connect(pid)


def live_run_key(pid, name: str, key_hash: str, conn=None) -> dict | None:
    """{key_hash, pass_hash} of an unexpired key of this connection, or None; the use is not counted."""
    with _on(pid, conn) as conn:
        return conn.execute("SELECT key_hash, pass_hash FROM connection.run_key"
                            " WHERE key_hash = %s AND name = %s AND expires_at > now()", (key_hash, name)).fetchone()


def count_run_key_use(pid, name: str, key_hash: str, conn=None) -> None:
    with _on(pid, conn) as conn:
        conn.execute("UPDATE connection.run_key SET uses = uses + 1, last_used_at = now()"
                     " WHERE key_hash = %s AND name = %s", (key_hash, name))


def revoke_run_keys(pid, pass_hash: str) -> int:
    """Delete the run keys issued under a pass; how many there were."""
    with connect(pid) as conn:
        return conn.execute("DELETE FROM connection.run_key WHERE pass_hash = %s", (pass_hash,)).rowcount
