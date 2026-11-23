"""The LangBiTe section of Test results.

LangBiTe's own tolerance check is shown as Pass / Fail, as the tool states it; the report computes no verdict.
Artifacts are never read (the Test results block lists their names and sizes).
"""
from __future__ import annotations

from aisc_report_plugin_interface import BaseToolRenderer
from aisc_report_plugin_interface.charts import svg
from aisc_report_plugin_interface.i18n import format_number, format_percent, translator_for

from . import parsing

DEFAULT_COLOURS = {"primary": "#000FDF", "text": "#000000", "grid": "#CCCCCC"}
CHART_ID = "pass_rate_by_concern"
#: LangBiTe's own tolerance check words, shown as Pass / Fail; other texts stay as written
CHECK_LABELS = {"Passed": "Pass", "Failed": "Fail"}


def _options(ctx) -> dict:
    options = getattr(ctx, "tool_options", None) or {}
    return {"show_charts": options.get("show_charts", True) is not False,
            "detail": "summary" if options.get("detail") == "summary" else "full"}


def _split(run):
    summary, groups, others = {}, [], []
    for m in run.measurements:
        name = m.get("name")
        if name in parsing.SUMMARY_NAMES and name not in summary:
            summary[name] = m
            continue
        if name in parsing.DASHBOARD_ONLY:
            continue
        parts = parsing.group_parts(name, m.get("dimensions"))
        if parts is not None:
            groups.append((parts, m))
        else:
            others.append(m)
    groups.sort(key=lambda g: (g[0][0], g[0][1], g[0][2]))
    return summary, groups, others


def _share(m):
    score = m.get("score")
    return float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else None


def _run_result(summary, t):
    """The line for LangBiTe's own check over all groups, or None when the tool wrote none.
    An empty run (b = 0) or an unreadable description is not evaluated, not failed."""
    m = summary.get(parsing.ALL_TOLERANCES)
    if m is None:
        return None
    description = m.get("description")
    checks = parsing.checks_passed(description)
    score = _share(m)
    if checks is None or checks[1] == 0 or score is None:
        return t("All tolerance checks: not evaluated ({description})", description=description or t("n/a"))
    if score >= 1:
        return t("All tolerance checks: Pass ({count} of {total} passed)", count=checks[0], total=checks[1])
    return t("All tolerance checks: Fail ({count} of {total} passed)", count=checks[0], total=checks[1])


class LANGBITEToolRenderer(BaseToolRenderer):
    tool_names = ("LangBiTe",)
    contract_version = 2
    chart_ids = {CHART_ID: "Pass rate by concern"}

    def verdict(self, run):
        return None

    def charts(self, run) -> list[dict]:
        _, groups, _ = _split(run)
        by_concern: dict[str, list[float]] = {}
        for parts, m in groups:
            share = _share(m)
            by_concern.setdefault(parts[0], [])
            if share is not None:
                by_concern[parts[0]].append(share)
        if not by_concern:
            return []
        series = [{"label": concern, "value": (sum(v) / len(v)) if v else None}
                  for concern, v in sorted(by_concern.items())]
        return [{"id": CHART_ID, "title": "Pass rate by concern", "kind": "hbar", "value_format": "percent",
                 "axis_min": 0, "axis_max": 1, "series": series}]

    def headline(self, run, ctx=None) -> list[dict]:
        """Values are formatted with `ctx` (decimal separator, percent format) when it is given; labels stay English message ids."""
        t = translator_for(ctx, __package__)
        summary, groups, _ = _split(run)
        items = []
        if parsing.OVERALL in summary:
            items.append({"label": "Overall pass rate", "value": format_percent(ctx, _share(summary[parsing.OVERALL]))})
        if parsing.ALL_TOLERANCES in summary:
            checks = parsing.checks_passed(summary[parsing.ALL_TOLERANCES].get("description"))
            if checks:
                items.append({"label": "Tolerance checks passed",
                              "value": t("{count} of {total}", count=checks[0], total=checks[1])})
        if summary or groups:
            items.append({"label": "Groups", "value": str(len(groups))})
        return items[:4]

    def render(self, run, ctx) -> str:
        t = translator_for(ctx, __package__)
        options = _options(ctx)
        summary, groups, others = _split(run)
        own = bool(summary or groups)

        summary_line = run_line = result_line = None
        if own:
            result_line = _run_result(summary, t)
            overall = summary.get(parsing.OVERALL)
            rate = format_percent(ctx, _share(overall)) if overall is not None else t("n/a")
            summary_line = t("Overall pass rate: {rate} across {groups} groups", rate=rate, groups=len(groups))
            success = summary.get(parsing.RUN_SUCCESS)
            if success is not None:
                if (_share(success) or 0) >= 1:
                    run_line = t("Run: finished")
                else:
                    run_line = t("Run: failed ({reason})", reason=success.get("description") or t("no reason given"))

        chart = chart_error = None
        if options["show_charts"]:
            for spec in self.charts(run):
                if any(item["value"] is not None for item in spec["series"]):
                    spec = {**spec, "title": t("Pass rate by concern")}
                    try:
                        chart = svg(spec, getattr(ctx, "chart_colours", None) or DEFAULT_COLOURS,
                                    decimal_separator=getattr(ctx, "decimal_separator", ".") or ".",
                                    percent_format=getattr(ctx, "percent_format", "{value}%") or "{value}%")
                    except ValueError:
                        chart_error = t("The chart could not be drawn.")

        rows = []
        if options["detail"] == "full":
            na = t("n/a")
            for parts, m in groups:
                d = parsing.group_description(m.get("description"))
                parsed = d["total"] is not None
                rows.append({
                    "parts": parts,
                    "passed": t("{count} of {total}", count=d["passed"], total=d["total"]) if parsed else na,
                    "failed": t("{count} of {total}", count=d["failed"], total=d["total"]) if parsed else na,
                    "rate": format_percent(ctx, _share(m)) if _share(m) is not None else na,
                    "tolerance": format_percent(ctx, d["tolerance"]) if parsed and d["tolerance"] is not None else na,
                    "check": t(CHECK_LABELS.get(d["check"], d["check"])) if parsed and d["check"] else na,
                })
        other_rows = []
        if options["detail"] == "full" or not own:
            for m in others:
                score = m.get("score")
                other_rows.append({"metric": m.get("metric") or m.get("name") or "",
                                   "value": format_number(ctx, score) if score is not None else t("n/a"),
                                   "unit": m.get("unit") or ""})
        return self.render_package_template(
            "templates/langbite.html.j2", t=t, summary_line=summary_line, result_line=result_line, run_line=run_line, chart=chart,
            chart_error=chart_error, rows=rows, other_rows=other_rows)
