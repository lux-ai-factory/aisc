"""Each project's helper models: a helper is a tool use (`connection.use`, its `tool_name` the helper's name) of a
connection (`connection.endpoint`, kind `provider`), in the project's own database
(project-template/0030_connectivity.sql; the old schema `helper` is no longer written).

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

# A helper as the routes have always read it: a tool use of a connection, by its tool name.
_VIEW = ("u.tool_name AS name, coalesce(u.label, e.label) AS label, e.base_url AS endpoint_url, u.roles,"
         " e.secret_ciphertext IS NOT NULL AS has_key, u.updated_at, u.updated_by, u.deleted_at, e.provider")
_FROM = "FROM connection.use u JOIN connection.endpoint e ON e.name = u.connection WHERE u.use = 'tool'"


def _addressed(row: dict | None) -> dict | None:
    """The row with the address tests call: the connection's own, or, for a hosted provider connection (which
    keeps none), where that provider takes OpenAI-style calls."""
    if row is not None and not row["endpoint_url"]:
        from platform_service import llm_catalogue

        if row["provider"] == "ollama":             # an Ollama connection without an address: the stack's own
            row = {**row, "endpoint_url": llm_store.ollama_default().rstrip("/") + "/v1"}
        else:
            row = {**row, "endpoint_url": llm_catalogue.chat_base_url(row["provider"] or "") or ""}
    return row


def list_models(pid, role: str | None = None) -> list[dict]:
    """The live helpers by name, optionally those with `role`; never the ciphertext."""
    with llm_store.connect(pid) as conn:
        rows = conn.execute(
            f"SELECT {_VIEW} {_FROM} AND u.deleted_at IS NULL AND e.deleted_at IS NULL"
            " AND (%s::text IS NULL OR %s = ANY (u.roles)) ORDER BY u.tool_name", (role, role)).fetchall()
    return [_addressed(r) for r in rows]


def get(pid, name: str, *, with_deleted: bool = False) -> dict | None:
    with llm_store.connect(pid) as conn:
        return _addressed(conn.execute(f"SELECT {_VIEW} {_FROM} AND u.tool_name = %s"
                                       + ("" if with_deleted else " AND u.deleted_at IS NULL"), (name,)).fetchone())


def use_as_tool(pid, connection: str, *, roles: list[str], subject: str | None) -> dict | None:
    """Make connection `connection` a test tool in `roles`, under its own name (Manage > Connectivity). The
    database refuses a connection that reaches the assessed system (ConnectionAssessed). None when a tool of that
    name already uses another connection."""
    try:
        _write_tool_use(pid, connection, roles, subject)
    except _NameElsewhere:
        return None
    return get(pid, connection)


class _NameElsewhere(Exception):
    """The tool name is another connection's: nothing is written, and the transaction (its event too) rolls back."""


def _write_tool_use(pid, connection: str, roles: list[str], subject: str | None) -> None:
    from platform_service.connection_store import ConnectionAssessed
    from platform_service.ledger import outbox

    import psycopg

    with llm_store.connect(pid) as conn, conn.transaction():
        outbox.emit_project(conn, "connection.use.saved", item_type="connection_use", item_id=connection,
                            details={"use": "tool", "connection": connection, "roles": list(roles)})
        try:
            written = conn.execute(
                "INSERT INTO connection.use (connection, use, roles, tool_name, updated_by)"
                " VALUES (%s, 'tool', %s, %s, %s)"
                " ON CONFLICT (tool_name) WHERE use = 'tool' DO UPDATE SET roles = EXCLUDED.roles,"
                "  updated_at = now(), updated_by = EXCLUDED.updated_by, deleted_at = NULL"
                " WHERE connection.use.connection = EXCLUDED.connection RETURNING id",
                (connection, list(roles), connection, subject)).fetchone()
        except psycopg.errors.RaiseException as exc:
            if "assessed system" in str(exc):
                raise ConnectionAssessed(connection) from None
            raise
        if written is None:
            raise _NameElsewhere(connection)


def stop_tool(pid, connection: str) -> bool:
    """Stop using connection `connection` as a test tool; the connection and its key stay. False when it was
    not one."""
    from platform_service.ledger import outbox

    with llm_store.connect(pid) as conn, conn.transaction():
        gone = conn.execute("UPDATE connection.use SET deleted_at = now() WHERE use = 'tool' AND connection = %s"
                            " AND deleted_at IS NULL RETURNING tool_name", (connection,)).fetchone()
        if gone is not None:
            outbox.emit_project(conn, "connection.use.removed", item_type="connection_use", item_id=connection,
                                details={"use": "tool"})
        return gone is not None


def _connection_for(conn, name: str) -> str:
    """The connection that holds helper `name`: the one it already has, else one named after it, else, when an
    other connection has that name, `<name>-helper`."""
    row = conn.execute("SELECT connection FROM connection.use WHERE use = 'tool' AND tool_name = %s",
                       (name,)).fetchone()
    if row is not None:
        return row["connection"]
    taken = conn.execute("SELECT 1 FROM connection.endpoint WHERE name = %s", (name,)).fetchone()
    return f"{name[:56]}-helper" if taken else name


# A connection the helpers page made: a self-hosted provider connection whose tool use carries the helper's label.
# A connection made a test tool on Connectivity has a use without a label, and stays the Connectivity page's.
_HELPERS_OWN = "e.kind = 'provider' AND e.provider = 'compatible' AND u.label IS NOT NULL"


def _helpers_own(conn, name: str) -> bool:
    """Whether helper `name` is new, or a tool use the helpers page made of a connection it made."""
    row = conn.execute(f"SELECT {_HELPERS_OWN} AS own {_FROM} AND u.tool_name = %s", (name,)).fetchone()
    return row is None or row["own"]


def save(pid, name: str, *, label: str, endpoint_url: str, roles: list[str], ciphertext=KEEP,
         subject: str | None, key_fingerprint: str | None = None) -> dict:
    """Insert, update or revive a helper; `ciphertext` KEEP keeps the stored key, None clears it."""
    from platform_service.connection_store import NameTaken
    from platform_service.ledger import outbox

    with llm_store.connect(pid) as conn, conn.transaction():
        old = conn.execute(f"SELECT e.base_url AS endpoint_url {_FROM} AND u.tool_name = %s", (name,)).fetchone()
        details = {"key": key_fingerprint} if key_fingerprint else {}
        details.update(endpoint_before=llm_store.logged_url(pid, old["endpoint_url"] if old else None),
                       endpoint_after=llm_store.logged_url(pid, endpoint_url), roles=list(roles))
        outbox.emit_project(conn, "helper.model.saved", item_type="helper_model", item_id=name, details=details)
        if not _helpers_own(conn, name):
            raise NameTaken(name)
        endpoint = _connection_for(conn, name)
        params = {"endpoint": endpoint, "name": name, "label": label, "url": endpoint_url, "roles": list(roles),
                  "subject": subject, "ciphertext": None if ciphertext is KEEP else ciphertext,
                  "set_key": ciphertext is not KEEP}
        made = conn.execute(
            "INSERT INTO connection.endpoint (name, label, kind, provider, base_url, secret_ciphertext, updated_by)"
            " VALUES (%(endpoint)s, %(label)s, 'provider', 'compatible', %(url)s, %(ciphertext)s, %(subject)s)"
            " ON CONFLICT (name) DO UPDATE SET label = EXCLUDED.label, base_url = EXCLUDED.base_url,"
            "  secret_ciphertext = CASE WHEN %(set_key)s THEN EXCLUDED.secret_ciphertext"
            "                      ELSE connection.endpoint.secret_ciphertext END,"
            "  updated_at = now(), updated_by = EXCLUDED.updated_by, deleted_at = NULL"
            " WHERE connection.endpoint.kind = 'provider' RETURNING name", params).fetchone()
        if made is None:
            raise NameTaken(endpoint)
        conn.execute(
            "INSERT INTO connection.use (connection, use, roles, label, tool_name, updated_by)"
            " VALUES (%(endpoint)s, 'tool', %(roles)s, %(label)s, %(name)s, %(subject)s)"
            " ON CONFLICT (tool_name) WHERE use = 'tool' DO UPDATE SET connection = EXCLUDED.connection,"
            "  roles = EXCLUDED.roles, label = EXCLUDED.label, updated_at = now(), updated_by = EXCLUDED.updated_by,"
            "  deleted_at = NULL", params)
        return conn.execute(f"SELECT {_VIEW} {_FROM} AND u.tool_name = %s", (name,)).fetchone()


def remove(pid, name: str) -> bool:
    """Mark a live helper removed; the rows stay. Its connection is marked removed and its key dropped only when
    the helpers page made that connection and nothing else uses it. False when there is no such helper."""
    from platform_service.ledger import outbox

    with llm_store.connect(pid) as conn, conn.transaction():
        gone = conn.execute("UPDATE connection.use SET deleted_at = now() WHERE use = 'tool' AND tool_name = %s"
                            " AND deleted_at IS NULL RETURNING connection, label", (name,)).fetchone()
        if gone is None:
            return False
        # the connection goes too only when the helpers page made it and nothing else uses it
        conn.execute("UPDATE connection.endpoint e SET deleted_at = now(), secret_ciphertext = NULL"
                     " WHERE e.name = %s AND e.kind = 'provider' AND e.provider = 'compatible' AND %s"
                     " AND NOT EXISTS (SELECT 1 FROM connection.use o WHERE o.connection = e.name"
                     "                 AND o.deleted_at IS NULL)", (gone["connection"], gone["label"] is not None))
        outbox.emit_project(conn, "helper.model.removed", item_type="helper_model", item_id=name)
        return True


def record_test(pid, name: str, ok: bool, status: int | None) -> None:
    """The Test button's outcome for the ledger: whether it worked and the status, never the endpoint's
    answer or the key."""
    from platform_service.ledger import outbox

    with llm_store.connect(pid) as conn, conn.transaction():
        outbox.emit_project(conn, "helper.model.tested", item_type="helper_model", item_id=name,
                            details={"ok": ok, "status": status})


def listing_of(pid, name: str) -> dict | None:
    """{"provider", "base_url", "ciphertext"} to list a live tool's models with its own connection: a provider
    connection's provider (base_url None for a hosted one, the stack's Ollama for an Ollama one without an address),
    or "compatible" at the address of another kind. None
    when there is no such tool."""
    with llm_store.connect(pid) as conn:
        row = conn.execute(f"SELECT e.provider, e.base_url, e.secret_ciphertext {_FROM} AND u.tool_name = %s"
                           " AND u.deleted_at IS NULL AND e.deleted_at IS NULL", (name,)).fetchone()
    if row is None:
        return None
    base_url = row["base_url"] or (llm_store.ollama_default() if row["provider"] == "ollama" else None)
    return {"provider": row["provider"] or "compatible", "base_url": base_url, "ciphertext": row["secret_ciphertext"]}


def resolve(pid, name: str) -> dict | None:
    """{"label", "endpoint_url", "roles", "api_key"} of a live helper, the key decrypted (None without
    one), or None when there is no such helper. Raises llm_store.KeyUnreadable or SecretsKeyError."""
    with llm_store.connect(pid) as conn:
        row = conn.execute(f"SELECT {_VIEW}, e.secret_ciphertext {_FROM} AND u.tool_name = %s"
                           " AND u.deleted_at IS NULL AND e.deleted_at IS NULL", (name,)).fetchone()
    if row is None:
        return None
    row = _addressed(row)
    key = llm_store.decrypt(name, row["secret_ciphertext"]) if row["secret_ciphertext"] else None
    return {"label": row["label"], "endpoint_url": row["endpoint_url"], "roles": row["roles"], "api_key": key}
