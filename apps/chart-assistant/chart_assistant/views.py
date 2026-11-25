"""Views: named queries the model reads instead of joining the engine's tables itself.

A view is a SELECT on the reader tables with a name and the meaning of each column. The model writes `FROM results`;
before the query runs, expand() writes the view into it as a WITH item, so the query that runs on the mock database,
that a person validates and that the fingerprint covers is the whole query, view included (R3). Nothing is created in
any database."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp


@dataclass(frozen=True)
class View:
    name: str
    meaning: str
    #: column name -> its meaning, in the order the model reads them
    columns: dict[str, str]
    sql: str
    #: the metrics a project must have results of for this view to be offered (a view of one test)
    needs: frozenset = field(default_factory=frozenset)
    #: one request in words, a colon, and the query answering it, shown to the model
    example: str = ""


_RESULTS_SQL = """SELECT met.name AS metric, m.score, m.dimensions, m.created_at AS measured_at,
       COALESCE(t.label, tc.name) AS target, t.kind AS target_kind,
       s.number AS system_version,
       r.number AS run, NULLIF(btrim(ep.name), '') AS run_name, e.status AS run_status
  FROM engine.aisc_backend_measurement m
  JOIN engine.aisc_backend_metric met ON met.id = m.metric_id
  JOIN engine.aisc_backend_observation o ON o.id = m.observation_id
  JOIN engine.aisc_backend_evaluation e ON e.id = o.evaluation_id
  JOIN (SELECT id, dense_rank() OVER (ORDER BY created_at, id) AS number
          FROM engine.aisc_backend_evaluation) r ON r.id = e.id
  LEFT JOIN engine.aisc_backend_evaluationplugin ep ON ep.id = o.evaluation_plugin_id
  LEFT JOIN engine.aisc_backend_evaluationinput ti ON ti.evaluation_plugin_id = ep.id AND ti.name = 'target'
  LEFT JOIN engine.aisc_backend_aicomponent tc ON tc.id = ti.component_id
  LEFT JOIN target.target t ON t.engine_component = tc.pid
  LEFT JOIN project.system s ON s.pid = e.system_id"""

BUILT_IN: dict[str, View] = {"results": View(
    name="results",
    meaning="one row per measured result, with its metric, what was tested, the AI card version and the run",
    columns={
        "metric": "the metric's name",
        "score": "the measured number",
        "dimensions": "the result's labels, read with dimensions->>'key'",
        "measured_at": "when it was stored",
        "target": "what was tested: the back-end, model or component, by its label",
        "target_kind": "system or component",
        "system_version": "the AI card version number",
        "run": "the run's number, as the dashboards show it",
        "run_name": "the name a person gave the run, if any",
        "run_status": "Done, Failed, ...",
    },
    sql=_RESULTS_SQL)}


def _defined_around(table: exp.Table, name: str) -> bool:
    from chart_assistant.query_check import _defined_in_scope
    return _defined_in_scope(table, name)


def _views_read(tree: exp.Expression, views: dict[str, View]) -> list[str]:
    """The views a query reads, in the order it first names them: bare names the query does not define itself."""
    read = []
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if table.db or name not in views or name in read or _defined_around(table, name):
            continue
        read.append(name)
    return read


def available(views: dict[str, View], metrics: Iterable[str]) -> dict[str, View]:
    """The views a project is offered: those whose metrics it has results of."""
    have = set(metrics)
    return {name: v for name, v in views.items() if v.needs <= have}


def expand(sql: str, views: dict[str, View]) -> str:
    """The query with every view it reads written in front of its own WITH items, and the views those read before them,
    each once; the query unchanged, byte for byte, when it reads none."""
    tree = sqlglot.parse_one(sql, read="postgres")
    read = _views_read(tree, views)
    if not read:
        return sql
    # a view another view reads goes first: PostgreSQL resolves a WITH item only from the items before it
    underneath = []
    for name in read:
        for below in _views_read(sqlglot.parse_one(views[name].sql, read="postgres"), views):
            if below not in underneath:
                underneath.append(below)
    read = [*underneath, *(name for name in read if name not in underneath)]
    items = [exp.CTE(this=sqlglot.parse_one(views[name].sql, read="postgres"), alias=exp.TableAlias(this=exp.to_identifier(name)))
             for name in read]
    with_ = tree.args.get("with")
    if with_ is not None:
        with_.set("expressions", [*items, *with_.expressions])
    else:
        tree.set("with", exp.With(expressions=items))
    return tree.sql(dialect="postgres")


def describe(views: dict[str, View]) -> str:
    """What the model reads of the views: each one's name and meaning, then its columns."""
    lines = []
    for view in views.values():
        lines.append(f"\n## {view.name}: {view.meaning}")
        lines.extend(f"- {column}: {meaning}" for column, meaning in view.columns.items())
        if view.example:
            lines.append(f"Example: {view.example}")
    return "\n".join(lines)
