"""The targets of one project, in its own database (schema `target`, project-template/0014_target.sql)."""
from __future__ import annotations

from platform_service import connection_store

_COLUMNS = ("key, kind, component_kind, label, first_card_number, last_card_number, engine_component,"
            " created_at, updated_at")


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
