"""The targets of one project, in its own database (schema `target`, project-template/0014_target.sql,
and the uploaded file of a component reached by one, 0028_target_file.sql)."""
from __future__ import annotations

from platform_service import connection_store

_COLUMNS = ("key, kind, component_kind, label, first_card_number, last_card_number, engine_component,"
            " file_component, file_name, file_size, file_sha256, file_uploaded_at, created_at, updated_at")


def all_targets(pid) -> list[dict]:
    with connection_store.connect(pid) as conn:
        return conn.execute(f"SELECT {_COLUMNS} FROM target.target ORDER BY kind DESC, label").fetchall()


def get(pid, key: str) -> dict | None:
    with connection_store.connect(pid) as conn:
        return conn.execute(f"SELECT {_COLUMNS} FROM target.target WHERE key = %s", (key,)).fetchone()


def ensure_system(pid, label: str) -> None:
    """The system target, labelled `label`; kept if it is there."""
    with connection_store.connect(pid) as conn:
        conn.execute("INSERT INTO target.target (key, kind, label) VALUES ('system', 'system', %s)"
                     " ON CONFLICT (key) DO NOTHING", (label,))


def set_system_label(pid, label: str) -> None:
    with connection_store.connect(pid) as conn:
        conn.execute("UPDATE target.target SET label = %s, updated_at = now() WHERE key = 'system' AND label <> %s",
                     (label, label))


def upsert_component(pid, key: str, label: str, component_kind: str, card_number: int) -> None:
    """A component the latest card has: made, or brought up to date and stamped with that card."""
    with connection_store.connect(pid) as conn:
        conn.execute(
            "INSERT INTO target.target (key, kind, component_kind, label, first_card_number, last_card_number)"
            " VALUES (%s, 'component', %s, %s, %s, %s)"
            " ON CONFLICT (key) DO UPDATE SET label = EXCLUDED.label, component_kind = EXCLUDED.component_kind,"
            " last_card_number = greatest(coalesce(target.target.last_card_number, 0), EXCLUDED.last_card_number),"
            " updated_at = now()",
            (key, component_kind, label, card_number, card_number))


def set_mirror(pid, key: str, component) -> None:
    with connection_store.connect(pid) as conn:
        conn.execute("UPDATE target.target SET engine_component = %s WHERE key = %s",
                     (str(component) if component else None, key))


def set_file_component(pid, key: str, component) -> None:
    """The engine component that holds this target's uploaded file, made before its first upload."""
    with connection_store.connect(pid) as conn:
        conn.execute("UPDATE target.target SET file_component = %s WHERE key = %s", (str(component), key))


def set_file(pid, key: str, name: str, size: int, sha256: str, by: str | None) -> None:
    """What the latest upload of this target's file was, once the engine holds its bytes; its event
    target.file.uploaded in the same transaction."""
    from platform_service.ledger import outbox

    with connection_store.connect(pid) as conn, conn.transaction():
        outbox.emit_project(conn, "target.file.uploaded", item_type="target", item_id=key,
                            details={"name": name, "size": size, "sha256": sha256})
        conn.execute("UPDATE target.target SET file_name = %s, file_size = %s, file_sha256 = %s,"
                     " file_uploaded_at = now(), file_uploaded_by = %s, updated_at = now() WHERE key = %s",
                     (name, size, sha256, by, key))
