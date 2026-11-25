"""What the model may know of a project: the reader tables and their columns (model.yaml), and the project's metrics
with their label keys, for categorical labels their values (D2), and for numbers the minimum and maximum of the first
finished run (the amended R1). Never a row, never a count."""
from __future__ import annotations

import functools
from pathlib import Path

import yaml

MODEL = Path(__file__).with_name("model.yaml")


@functools.cache
def fixed_model() -> dict:
    return yaml.safe_load(MODEL.read_text())


#: the tables the read-only roles may read (scripts/report-grants.sh), and so the only ones a query may name
READERS = frozenset(fixed_model())


def dimension_keys_of(project: dict) -> frozenset[str]:
    """Every dimension key of every metric of the project: the only keys a query may read from dimensions."""
    return frozenset(key for metric in project.get("metrics", []) for key in metric.get("dimensions", {}))


def for_model(project: dict, views: dict | None = None) -> str:
    """The text the model reads: the views first, then the project's targets, the tables and columns (with meanings
    where written), then the project's metrics. project: {"targets": [labels], "metrics": [{"name", "dimensions":
    {key: {"type", "values": [..] or None}}}]}; any count in it is left out."""
    lines = []
    if views:
        from chart_assistant.views import describe
        lines.append("# Views: read these first. They already join each result to its metric, target, version and run.")
        lines.append(describe(views))
    if project.get("targets"):
        labels = ", ".join(repr(str(label)) for label in project["targets"])
        lines.append(f"\n# This project's targets (results.target): {labels}\n")
    lines.append("# Tables you may query (PostgreSQL). Columns: name (type): meaning.")
    for table, spec in sorted(fixed_model().items()):
        if not spec.get("meaning"):
            continue
        lines.append(f"\n## {table}: {spec['meaning']}")
        for column, c in spec["columns"].items():
            lines.append(f"- {column} ({c['type']}){': ' + c['meaning'] if c.get('meaning') else ''}")
    others = sorted(t for t, s in fixed_model().items() if not s.get("meaning"))
    lines.append("\nOther tables you may read, by name only: " + ", ".join(others))
    lines.append("\n# This project's results: metrics (engine.aisc_backend_metric.name) and the keys of their dimensions")
    for metric in project.get("metrics", []):
        lines.append(f"\n## metric {metric['name']!r}")
        span = metric.get("score")
        if span:
            lines.append(f"- score: between {span['min']} and {span['max']} in the first run")
        for key, d in sorted(metric.get("dimensions", {}).items()):
            values = d.get("values")
            if values:
                shown = ": one of " + ", ".join(repr(v) for v in values)
            elif d.get("min") is not None:
                shown = f": a number between {d['min']} and {d['max']} in the first run"
            else:
                shown = ": free text, values not shown"
            lines.append(f"- dimensions->>'{key}' ({d.get('type', 'text')}){shown}")
    return "\n".join(lines)
