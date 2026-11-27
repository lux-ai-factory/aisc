"""How many people check each kind of task.

One number per kind, 0 to 5, in work.staffing_rule: one row per change, the latest wins, and a kind with no
row needs no checker, so a new project starts as the light preset. Who may change it (an owner) is decided by
the route.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from psycopg.rows import tuple_row

from platform_service.work import presets
from platform_service.work.kinds import KINDS


@dataclass(frozen=True)
class Rule:
    kind: str
    checkers: int
    set_by: str | None
    set_at: datetime | None


def _run(conn, statement: str, params=()):
    return conn.cursor(row_factory=tuple_row).execute(statement, params)


def rules(conn) -> list[Rule]:
    """The rule of every kind, in the order of the steps."""
    latest = {row[0]: row for row in _run(
        conn, "select distinct on (kind) kind, checkers, set_by_name, set_at from work.staffing_rule"
              " order by kind, set_at desc, id desc").fetchall()}
    return [Rule(kind, *latest[kind][1:]) if kind in latest else Rule(kind, 0, None, None) for kind in KINDS]


def checkers(conn, kind: str) -> int:
    """How many checkers a task of `kind` needs now."""
    row = _run(conn, "select checkers from work.staffing_rule where kind = %s order by set_at desc, id desc"
                     " limit 1", (kind,)).fetchone()
    return row[0] if row else 0


def set_checkers(conn, kind: str, number: int, *, by_subject: str, by_name: str) -> None:
    if kind not in KINDS:
        raise KeyError(kind)
    _run(conn, "insert into work.staffing_rule (kind, checkers, set_by_subject, set_by_name) values (%s, %s, %s, %s)",
         (kind, number, by_subject, by_name))


def apply_preset(conn, preset: str, *, by_subject: str, by_name: str) -> dict[str, int]:
    """Every kind set as the preset says, one row each. An unknown preset is a KeyError."""
    numbers = presets.checkers(preset)
    for kind, number in numbers.items():
        set_checkers(conn, kind, number, by_subject=by_subject, by_name=by_name)
    return numbers
