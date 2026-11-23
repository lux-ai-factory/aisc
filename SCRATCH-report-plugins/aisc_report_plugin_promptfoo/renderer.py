"""The promptfoo section of Test results.

One two-column table of the six measurements; direction words come from the unit. No verdict.
pass_rate and fail_rate are promptfoo's own results and are labelled Pass and Fail.
Artifacts (promptfoo_results.json and the logs hold prompts and answers) are never read.
"""
from __future__ import annotations

from aisc_report_plugin_interface import BaseToolRenderer
from aisc_report_plugin_interface.charts import svg
from aisc_report_plugin_interface.i18n import format_number, format_percent, translator_for

from . import parsing

DEFAULT_COLOURS = {"primary": "#000FDF", "text": "#000000", "grid": "#CCCCCC"}
CHART_ID = "rates"
RATE_LABELS = {"pass_rate": "Pass", "fail_rate": "Fail", "refusal_rate": "Refusal rate"}
NOTE = ("Pass and Fail are promptfoo's own results: a test passes when all of its assertions pass. "
        "The values are shares of the tests.")


def _options(ctx) -> dict:
    options = getattr(ctx, "tool_options", None) or {}
    return {"show_charts": options.get("show_charts", True) is not False,
            "detail": "summary" if options.get("detail") == "summary" else "full"}


def _score(m):
    if m is None:
        return None
    score = m.get("score")
    return float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else None


def _split(run):
    known, others = {}, []
    for m in run.measurements:
        name = m.get("name")
        if name in parsing.KNOWN and name not in known:
            known[name] = m
        else:
            others.append(m)
    return known, others


class PROMPTFOOToolRenderer(BaseToolRenderer):
    tool_names = ("Promptfoo", "promptfoo")
    contract_version = 2
    chart_ids = {CHART_ID: "Pass, fail and refusal rates"}

    def verdict(self, run):
        return None

    def charts(self, run) -> list[dict]:
        known, _ = _split(run)
        series = [{"label": RATE_LABELS[name], "value": _score(known[name])}
                  for name in parsing.RATES if _score(known.get(name)) is not None]
        if not series:
            return []
        return [{"id": CHART_ID, "title": "Pass, fail and refusal rates", "kind": "bar", "value_format": "percent",
                 "axis_min": 0, "axis_max": 1, "series": series}]

    def headline(self, run, ctx=None) -> list[dict]:
        """Values are formatted with `ctx` (decimal separator, percent format) when it is given; labels stay English message ids."""
        known, _ = _split(run)
        items = []
        if _score(known.get("pass_rate")) is not None:
            items.append({"label": "Pass", "value": format_percent(ctx, _score(known["pass_rate"]))})
        if _score(known.get("n_tests")) is not None:
            items.append({"label": "Tests run", "value": str(int(round(_score(known["n_tests"]))))})
        return items

    def render(self, run, ctx) -> str:
        t = translator_for(ctx, __package__)
        options = _options(ctx)
        known, others = _split(run)

        def label(text, name):
            m = known.get(name)
            d = parsing.direction(m.get("unit")) if m is not None else None
            if d == "higher":
                return t("{label} (higher is better)", label=text)
            if d == "lower":
                return t("{label} (lower is better)", label=text)
            return text

        not_reported = t("not reported")
        rows = []
        if known:
            tests = _score(known.get("n_tests"))
            rows.append((label(t("Tests run"), "n_tests"), str(int(round(tests))) if tests is not None else not_reported))
            for name in parsing.RATES:
                text = t(RATE_LABELS[name])
                value = _score(known.get(name))
                rows.append((label(text, name), format_percent(ctx, value) if value is not None else not_reported))
            latency = _score(known.get("mean_latency_ms"))
            rows.append((label(t("Mean latency"), "mean_latency_ms"),
                         t("{value} ms", value=format_number(ctx, latency, 0)) if latency is not None else not_reported))
            cost = _score(known.get("total_cost"))
            rows.append((label(t("Total cost"), "total_cost"),
                         t("{value} USD", value=format_number(ctx, cost, 4)) if cost is not None else not_reported))
        pass_fail_note = t(NOTE) if any(_score(known.get(n)) is not None for n in ("pass_rate", "fail_rate")) \
            else None
        refusal_note = t("Refusal rate: estimated from the grader's reasons.") \
            if _score(known.get("refusal_rate")) is not None else None
        empty = t("promptfoo wrote no results for this run.") if not run.measurements else None

        chart = chart_error = None
        if options["show_charts"]:
            for spec in self.charts(run):
                names = {label: t(label) for label in RATE_LABELS.values()}
                spec = {**spec, "title": t("Pass, fail and refusal rates"),
                        "series": [{**item, "label": names.get(item["label"], item["label"])}
                                   for item in spec["series"]]}
                try:
                    chart = svg(spec, getattr(ctx, "chart_colours", None) or DEFAULT_COLOURS,
                                decimal_separator=getattr(ctx, "decimal_separator", ".") or ".",
                                percent_format=getattr(ctx, "percent_format", "{value}%") or "{value}%")
                except ValueError:
                    chart_error = t("The chart could not be drawn.")

        other_rows = []
        if options["detail"] == "full" or not known:
            for m in others:
                score = m.get("score")
                other_rows.append({"metric": m.get("metric") or m.get("name") or "",
                                   "value": format_number(ctx, score) if score is not None else t("n/a"),
                                   "unit": m.get("unit") or ""})
        return self.render_package_template(
            "templates/promptfoo.html.j2", t=t, rows=rows, pass_fail_note=pass_fail_note, refusal_note=refusal_note, empty=empty, chart=chart,
            chart_error=chart_error, other_rows=other_rows)
