"""The mock database of a project: the reader tables with the real structure and invented rows.

The rows follow the project's description (its targets, metrics and label values) so a chart query written for the
real data runs here. Numbers are drawn between the minimum and maximum of the project's first finished run (a simple
triangular distribution peaked in the middle; whole numbers stay whole), the only thing of the real values the
description carries, and they hold the awkward cases on purpose (an empty value, a duplicated row, a missing score,
a combination left out), so a query that only works on clean data shows it on mock first. Nothing real is in it."""
from __future__ import annotations

import itertools
import json
import math
import random
import uuid
from datetime import datetime, timedelta, timezone

#: how a described type is created; the arrays of the reader tables are all text arrays
_TYPES = {"ARRAY": "text[]", "USER-DEFINED": "text"}
MAX_COMBINATIONS = 400
FREE_TEXT_POOL = 3


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def ddl(model: dict) -> str:
    """CREATE SCHEMA and CREATE TABLE for every described table: columns and types only, no constraint."""
    schemas = sorted({t.split(".")[0] for t in model})
    out = [f"CREATE SCHEMA IF NOT EXISTS {_quote_ident(s)};" for s in schemas]
    for table, spec in sorted(model.items()):
        schema, name = table.split(".")
        cols = ", ".join(f"{_quote_ident(c)} {_TYPES.get(v['type'], v['type'])}" for c, v in spec["columns"].items())
        out.append(f"CREATE TABLE {_quote_ident(schema)}.{_quote_ident(name)} ({cols});")
    return "\n".join(out) + "\n"


def _uuid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def _free_text(rng: random.Random, key: str) -> str:
    return f"{key.capitalize()} {'ABC'[rng.randrange(FREE_TEXT_POOL)]}"


def _draw(rng: random.Random, span: dict | None):
    """A number between span's min and max (0 to 1 without a span); whole when the real values are whole."""
    low, high = (span or {}).get("min", 0), (span or {}).get("max", 1)
    if (span or {}).get("whole"):
        return rng.randint(int(low), int(high))
    if low == high:
        return low
    return round(rng.triangular(low, high), 3)


def _label_span(dimension: dict) -> dict:
    """A numeric label's range as _draw reads it: whole when said so, or when both its ends are whole numbers (the
    description gives a label's range without saying whether its values are whole)."""
    low, high = dimension["min"], dimension["max"]
    bounds_whole = all(isinstance(v, int) and not isinstance(v, bool) for v in (low, high))
    return {"min": low, "max": high, "whole": dimension.get("whole", bounds_whole)}


def _combinations(rng: random.Random, values: list[list]) -> list[tuple]:
    """Every combination of the label values, or MAX_COMBINATIONS distinct ones drawn at random when there are more:
    drawn one by one, never by building them all first (six keys of 40 values are four billion)."""
    sizes = [len(v) for v in values]
    if math.prod(sizes) <= MAX_COMBINATIONS:
        return list(itertools.product(*values))
    drawn: dict[tuple, None] = {}
    while len(drawn) < MAX_COMBINATIONS:
        drawn[tuple(rng.randrange(n) for n in sizes)] = None
    return [tuple(v[i] for v, i in zip(values, at, strict=True)) for at in drawn]


def rows(project: dict, rng: random.Random) -> dict[str, list[dict]]:
    """table -> rows, invented: one run per target, every metric's label combinations (at most MAX_COMBINATIONS)."""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # two AI card versions, so a chart by version has something to show
    versions = [_uuid(rng), _uuid(rng)]
    out: dict[str, list[dict]] = {t: [] for t in (
        "project.system", "target.target", "engine.aisc_backend_aicomponent", "engine.aisc_backend_evaluation",
        "engine.aisc_backend_evaluationplugin", "engine.aisc_backend_evaluationinput", "engine.aisc_backend_observation",
        "engine.aisc_backend_metric", "engine.aisc_backend_measurement")}
    for number, pid in enumerate(versions, 1):
        out["project.system"].append({"pid": pid, "number": number, "name": "Mock system", "created_at": start})
    metrics = project.get("metrics", [])
    for j, metric in enumerate(metrics, 1):
        out["engine.aisc_backend_metric"].append({"id": j, "pid": _uuid(rng), "name": metric["name"], "created_at": start})
    measurement_id = 0
    targets = project.get("targets") or ["Target A", "Target B"]
    for i, label in enumerate(targets, 1):
        component = _uuid(rng)
        when = start + timedelta(days=i)
        out["engine.aisc_backend_aicomponent"].append({"id": i, "pid": component, "name": label, "created_at": when})
        out["target.target"].append({"key": f"component:{i}", "kind": "component", "label": label,
                                     "engine_component": component, "created_at": when})
        # the last run did not finish, and the second half of the runs are of the second card version
        status = "Failed" if i == len(targets) and len(targets) > 1 else "Done"
        out["engine.aisc_backend_evaluation"].append({"id": i, "pid": _uuid(rng), "status": status, "created_at": when,
                                                      "system_id": versions[0 if i <= len(targets) // 2 else 1]})
        out["engine.aisc_backend_evaluationplugin"].append({"id": i, "pid": _uuid(rng), "name": f"Mock run {i}",
                                                            "evaluation_id": i, "status": status, "created_at": when})
        out["engine.aisc_backend_evaluationinput"].append({"id": i, "pid": _uuid(rng), "name": "target", "component_id": i,
                                                           "evaluation_plugin_id": i, "value": {}, "created_at": when})
        out["engine.aisc_backend_observation"].append({"id": i, "pid": _uuid(rng), "observer": "mock", "tool": "mock",
                                                       "evaluation_id": i, "evaluation_plugin_id": i, "created_at": when})
        for j, metric in enumerate(metrics, 1):
            dims = metric.get("dimensions", {})
            labelled = {k: d["values"] for k, d in sorted(dims.items()) if d.get("values")}
            ranged = {k: d for k, d in sorted(dims.items()) if not d.get("values") and d.get("type") == "number"
                      and d.get("min") is not None and d.get("max") is not None}
            free = [k for k, d in sorted(dims.items()) if not d.get("values") and k not in ranged]
            combos = _combinations(rng, list(labelled.values()))
            made = []
            for combo in combos:
                d = dict(zip(labelled, combo))
                d.update({k: _free_text(rng, k) for k in free})
                d.update({k: _draw(rng, _label_span(r)) for k, r in ranged.items()})
                measurement_id += 1
                made.append({"id": measurement_id, "pid": _uuid(rng), "name": metric["name"], "metric_id": j,
                             "observation_id": i, "score": _draw(rng, metric.get("score")), "dimensions": d,
                             "created_at": when})
            if len(made) > 3:
                made.pop(rng.randrange(len(made)))                                   # a combination left out
                if free:
                    made[0]["dimensions"][free[0]] = ""                              # an empty value
                made[1]["score"] = None                                             # a missing score
                measurement_id += 1
                made.append({**made[2], "id": measurement_id, "pid": _uuid(rng),     # a duplicated row
                             "dimensions": dict(made[2]["dimensions"])})
            out["engine.aisc_backend_measurement"].extend(made)
    return out


def _literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, dict):
        return "'" + json.dumps(value, ensure_ascii=False).replace("'", "''") + "'::jsonb"
    if isinstance(value, datetime):
        return f"'{value.isoformat()}'::timestamptz"
    return "'" + str(value).replace("'", "''") + "'"


def inserts(rows_by_table: dict[str, list[dict]]) -> str:
    out = []
    for table, rows_ in rows_by_table.items():
        schema, name = table.split(".")
        for r in rows_:
            cols = ", ".join(_quote_ident(c) for c in r)
            out.append(f"INSERT INTO {_quote_ident(schema)}.{_quote_ident(name)} ({cols}) VALUES "
                       f"({', '.join(_literal(v) for v in r.values())});")
    return "\n".join(out) + "\n"
