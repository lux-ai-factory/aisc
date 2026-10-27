"""Each project's helper models, in the project's own database (schema `helper`).

A helper is a model the assessment itself uses (judge, attacker, grader, embedder, generator), not
part of the AI system being assessed. Its key is encrypted with the same Fernet key list as the
LLM keys (see llm_store) and is only decrypted by `resolve`, for the routes that hand it to the
engine or the worker. Every other function returns `has_key`, never the ciphertext.
"""
from __future__ import annotations

from platform_service import llm_store

#: What a helper can be used as, in the order the page shows them.
ROLES = ("judge", "attacker", "grader", "embedder", "generator")
KEEP = llm_store.KEEP

_VIEW = "name, label, endpoint_url, roles, ciphertext IS NOT NULL AS has_key, updated_at, updated_by, deleted_at"


def list_models(pid, role: str | None = None) -> list[dict]:
    """The live helpers by name, optionally those with `role`; never the ciphertext."""
    with llm_store.connect(pid) as conn:
        return conn.execute(
            f"SELECT {_VIEW} FROM helper.model WHERE deleted_at IS NULL"
            " AND (%s::text IS NULL OR %s = ANY (roles)) ORDER BY name", (role, role)).fetchall()


def get(pid, name: str, *, with_deleted: bool = False) -> dict | None:
    with llm_store.connect(pid) as conn:
        return conn.execute(
            f"SELECT {_VIEW} FROM helper.model WHERE name = %s"
            + ("" if with_deleted else " AND deleted_at IS NULL"), (name,)).fetchone()


def save(pid, name: str, *, label: str, endpoint_url: str, roles: list[str], ciphertext=KEEP,
         subject: str | None, key_fingerprint: str | None = None) -> dict:
    """Insert, update or revive a helper; `ciphertext` KEEP keeps the stored key, None clears it."""
    from platform_service.ledger import outbox

    params = {"name": name, "label": label, "url": endpoint_url, "roles": list(roles), "subject": subject,
              "ciphertext": None if ciphertext is KEEP else ciphertext, "set_key": ciphertext is not KEEP}
    with llm_store.connect(pid) as conn, conn.transaction():
        old = conn.execute("SELECT endpoint_url FROM helper.model WHERE name = %s", (name,)).fetchone()
        details = {"key": key_fingerprint} if key_fingerprint else {}
        details.update(endpoint_before=llm_store.logged_url(pid, old["endpoint_url"] if old else None),
                       endpoint_after=llm_store.logged_url(pid, endpoint_url), roles=list(roles))
        outbox.emit_project(conn, "helper.model.saved", item_type="helper_model", item_id=name, details=details)
        return conn.execute(
            "INSERT INTO helper.model (name, label, endpoint_url, ciphertext, roles, updated_by)"
            " VALUES (%(name)s, %(label)s, %(url)s, %(ciphertext)s, %(roles)s, %(subject)s)"
            " ON CONFLICT (name) DO UPDATE SET label = EXCLUDED.label, endpoint_url = EXCLUDED.endpoint_url,"
            "  roles = EXCLUDED.roles,"
            "  ciphertext = CASE WHEN %(set_key)s THEN EXCLUDED.ciphertext ELSE helper.model.ciphertext END,"
            "  updated_at = now(), updated_by = EXCLUDED.updated_by, deleted_at = NULL"
            f" RETURNING {_VIEW}", params).fetchone()


def remove(pid, name: str) -> bool:
    """Mark a live helper removed and drop its key; the row stays. False when there is none."""
    from platform_service.ledger import outbox

    with llm_store.connect(pid) as conn, conn.transaction():
        gone = conn.execute("UPDATE helper.model SET deleted_at = now(), ciphertext = NULL"
                            " WHERE name = %s AND deleted_at IS NULL RETURNING name", (name,)).fetchone() is not None
        if gone:
            outbox.emit_project(conn, "helper.model.removed", item_type="helper_model", item_id=name)
        return gone


def record_test(pid, name: str, ok: bool, status: int | None) -> None:
    """The Test button's outcome for the ledger: whether it worked and the status, never the endpoint's
    answer or the key."""
    from platform_service.ledger import outbox

    with llm_store.connect(pid) as conn, conn.transaction():
        outbox.emit_project(conn, "helper.model.tested", item_type="helper_model", item_id=name,
                            details={"ok": ok, "status": status})


def resolve(pid, name: str) -> dict | None:
    """{"label", "endpoint_url", "roles", "api_key"} of a live helper, the key decrypted (None without
    one), or None when there is no such helper. Raises llm_store.KeyUnreadable or SecretsKeyError."""
    with llm_store.connect(pid) as conn:
        row = conn.execute("SELECT label, endpoint_url, roles, ciphertext FROM helper.model"
                           " WHERE name = %s AND deleted_at IS NULL", (name,)).fetchone()
    if row is None:
        return None
    key = llm_store.decrypt(name, row["ciphertext"]) if row["ciphertext"] else None
    return {"label": row["label"], "endpoint_url": row["endpoint_url"], "roles": row["roles"], "api_key": key}


def rotate(conn, multi) -> tuple[int, int, int]:
    """(rotated, unreadable, changed_meanwhile) for one project's helper keys, on an open connection;
    the same contract as connection_store.rotate."""
    if conn.execute("SELECT to_regclass('helper.model')").fetchone()[0] is None:
        return 0, 0, 0
    rotated = unreadable = meanwhile = 0
    for name, token in conn.execute("SELECT name, ciphertext FROM helper.model"
                                    " WHERE ciphertext IS NOT NULL").fetchall():
        try:
            fresh = multi.rotate(token.encode()).decode()
        except llm_store.InvalidToken:
            unreadable += 1
            continue
        # only if it is still the key read: one saved meanwhile is under the newest key already
        if conn.execute("UPDATE helper.model SET ciphertext = %s WHERE name = %s AND ciphertext = %s",
                        (fresh, name, token)).rowcount:
            rotated += 1
        else:
            meanwhile += 1
    return rotated, unreadable, meanwhile
