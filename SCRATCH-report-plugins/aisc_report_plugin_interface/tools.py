"""The tool-renderer contract inside the Test results block.

A tool renderer draws one plugin run of the engine (a ToolRun: read-only, no database session).
It is matched to the engine's plugin row by normalised names (see tool_keys).
"""
from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from . import templating


def normalise_tool_name(name: str) -> str:
    """Uppercase, with spaces, dashes and underscores removed."""
    return str(name).upper().replace(" ", "").replace("-", "").replace("_", "")


def tool_keys(display_name=None, name=None, package_name=None) -> set[str]:
    """Every normalised name an engine plugin row is known by."""
    raw: list[str] = []
    if display_name:
        raw.append(display_name)
    if name:
        raw.append(name)
        for suffix in ("EvaluationPlugin", "Plugin"):
            if name.endswith(suffix) and len(name) > len(suffix):
                raw.append(name[: -len(suffix)])
                break
    if package_name:
        raw.append(package_name[len("aisc-plugin-"):] if package_name.startswith("aisc-plugin-") else package_name)
    return {normalise_tool_name(r) for r in raw if r}


class BaseToolRenderer(ABC):
    tool_names: tuple[str, ...] = ()
    #: 1 for the first contract; 2 for a renderer that implements headline() and charts()
    contract_version: int = 1
    #: chart id to English label, naming what charts() can return
    chart_ids: dict = {}

    @abstractmethod
    def render(self, run, ctx) -> str:
        """Return an HTML fragment for one run. Tool options: getattr(ctx, "tool_options", {})."""

    def headline(self, run, ctx=None) -> list[dict]:
        """At most 4 {label, value, note?} items of plain text naming the run's main numbers.

        `ctx` is the report's block context (language, decimal separator, percent format, translate_for).
        When it is given, format each value with it (format_number(ctx, ...),
        format_percent(ctx, ...), translator_for(ctx, package)); labels and notes stay English message ids,
        the caller translates them. Callers go through headline_items(), which also serves renderers whose
        headline() takes the run only."""
        return []

    def charts(self, run) -> list[dict]:
        """Chart specs (see charts.svg) that the chart block may draw."""
        return []

    def verdict(self, run):
        """"pass", "fail" or None when the tool defines no threshold."""
        return None

    @classmethod
    def matches(cls, plugin_row: Mapping) -> bool:
        keys = tool_keys(plugin_row.get("display_name"), plugin_row.get("name"), plugin_row.get("package_name"))
        return any(normalise_tool_name(n) in keys for n in cls.tool_names)

    def render_package_template(self, template_relative_path: str, **context: Any) -> str:
        # the folder of the module this class is in: a one-file plugin from a path has one too
        return templating.render_class_template(self.__class__, template_relative_path, **context)


def _takes_context(method) -> bool:
    try:
        params = inspect.signature(method).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.kind is p.VAR_KEYWORD or p.name == "ctx" for p in params)


def headline_items(renderer, run, ctx) -> list:
    """The renderer's headline for `run`, formatted for the report when its headline() accepts `ctx`."""
    method = renderer.headline
    items = method(run, ctx=ctx) if _takes_context(method) else method(run)
    return list(items or [])


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


@dataclass(frozen=True)
class ToolRun:
    evaluation: Mapping
    evaluation_plugin: Mapping
    tool: Mapping
    components: tuple
    observations: tuple
    measurements: tuple
    artifacts: tuple
    #: what the run assessed: {key, kind ("system" | "component"), component_kind, label, card_version,
    #: status ("current" | "stale" | "not a target")}, or None for a run without a target
    target: Mapping | None = None

    def __post_init__(self) -> None:
        for f in ("evaluation", "evaluation_plugin", "tool", "components", "observations",
                  "measurements", "artifacts", "target"):
            object.__setattr__(self, f, _freeze(getattr(self, f)))
