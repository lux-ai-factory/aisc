"""The StrongREJECT section of Test results.

The plugin writes 0.0 when it fails, which would read as "perfectly safe": a summary value whose
description is not the plugin's success text is shown as "not scored: {description}" and left out
of charts and the headline. No verdict and no colour bands. Artifacts are never read.
"""
from __future__ import annotations

from aisc_report_plugin_interface import BaseToolRenderer
from aisc_report_plugin_interface.charts import svg
from aisc_report_plugin_interface.i18n import format_number, translator_for

from . import parsing

DEFAULT_COLOURS = {"primary": "#000FDF", "text": "#000000", "grid": "#CCCCCC"}
CHART_ID = "harmfulness_by_jailbreak"


def _options(ctx) -> dict:
    options = getattr(ctx, "tool_options", None) or {}
    return {"show_charts": options.get("show_charts", True) is not False,
            "detail": "summary" if options.get("detail") == "summary" else "full"}


def _score(m):
    score = m.get("score")
    return float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else None


def _split(run):
    summary, jailbreaks, others = {}, [], []
    for m in run.measurements:
        name = m.get("name")
        if name in parsing.SUMMARY_NAMES and name not in summary:
            summary[name] = m
            continue
        key = parsing.jailbreak_key(name)
        if key is not None:
            jailbreaks.append((key, m))
        else:
            others.append(m)
    jailbreaks.sort(key=lambda j: (j[0] != "none", j[0]))
    return summary, jailbreaks, others


def _scored(summary, name):
    m = summary.get(name)
    return m is not None and parsing.is_scored(name, m.get("description")) and _score(m) is not None


class STRONGREJECTToolRenderer(BaseToolRenderer):
    tool_names = ("StrongREJECT",)
    contract_version = 2
    chart_ids = {CHART_ID: "Harmfulness by jailbreak"}

    def verdict(self, run):
        return None

    def charts(self, run) -> list[dict]:
        _, jailbreaks, _ = _split(run)
        series = [{"label": key, "value": _score(m)} for key, m in jailbreaks]
        if not series:
            return []
        return [{"id": CHART_ID, "title": "Harmfulness by jailbreak", "kind": "bar", "value_format": "number",
                 "axis_min": 0, "axis_max": 1, "series": series}]

    def headline(self, run, ctx=None) -> list[dict]:
        """The one figure of a report's key figures: jailbreak resistance. Values are formatted with `ctx` (decimal separator, percent format) when it is given; labels and notes stay English message ids."""
        summary, _, _ = _split(run)
        items = []
        if _scored(summary, parsing.RESISTANCE):
            items.append({"label": "Jailbreak resistance",
                          "value": format_number(ctx, _score(summary[parsing.RESISTANCE])),
                          "note": "higher is safer"})
        return items

    def render(self, run, ctx) -> str:
        t = translator_for(ctx, __package__)
        options = _options(ctx)
        summary, jailbreaks, others = _split(run)

        def value_or_reason(name):
            m = summary[name]
            if _scored(summary, name):
                return format_number(ctx, _score(m))
            return t("not scored: {description}", description=(m.get("description") or "").strip())

        key_rows = []
        if parsing.HARMFULNESS in summary:
            key_rows.append((t("Harmfulness (mean, 0 to 1, lower is safer)"), value_or_reason(parsing.HARMFULNESS)))
        if parsing.RESISTANCE in summary:
            key_rows.append((t("Jailbreak resistance (1 minus harmfulness, higher is safer)"),
                             value_or_reason(parsing.RESISTANCE)))
        if parsing.BASELINE in summary:
            key_rows.append((t("Baseline harmfulness, no jailbreak"), value_or_reason(parsing.BASELINE)))
        if parsing.WORST in summary:
            if _scored(summary, parsing.WORST):
                key = parsing.worst_key(summary[parsing.WORST].get("description")) or t("n/a")
                key_rows.append((t("Worst jailbreak: {key}", key=key), value_or_reason(parsing.WORST)))
            else:
                key_rows.append((t("Worst jailbreak"), value_or_reason(parsing.WORST)))

        notices = []
        if summary and not any(_scored(summary, name) for name in summary):
            notices.append(t("StrongREJECT did not produce scores in this run."))

        chart = chart_error = None
        if options["show_charts"]:
            for spec in self.charts(run):
                if any(item["value"] is not None for item in spec["series"]):
                    spec = {**spec, "title": t("Harmfulness by jailbreak")}
                    try:
                        chart = svg(spec, getattr(ctx, "chart_colours", None) or DEFAULT_COLOURS,
                                    decimal_separator=getattr(ctx, "decimal_separator", ".") or ".",
                                    percent_format=getattr(ctx, "percent_format", "{value}%") or "{value}%")
                    except ValueError:
                        chart_error = t("The chart could not be drawn.")

        rows, other_rows = [], []
        own = bool(summary or jailbreaks)
        if options["detail"] == "full":
            for key, m in jailbreaks:
                n = parsing.prompts(m.get("description"))
                rows.append({"key": key,
                             "value": format_number(ctx, _score(m), 3) if _score(m) is not None else t("n/a"),
                             "prompts": str(n) if n is not None else t("n/a")})
        if options["detail"] == "full" or not own:
            for m in others:
                score = m.get("score")
                other_rows.append({"metric": m.get("metric") or m.get("name") or "",
                                   "value": format_number(ctx, score) if score is not None else t("n/a"),
                                   "unit": m.get("unit") or ""})
        return self.render_package_template(
            "templates/strongreject.html.j2", t=t, key_rows=key_rows, notices=notices, chart=chart,
            chart_error=chart_error, rows=rows, other_rows=other_rows)
