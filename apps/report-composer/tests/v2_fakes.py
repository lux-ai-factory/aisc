"""The renderer as the composer sees it after report run v2 (2026-09-24, 01-specs.md), for the v2 tests.

Test infrastructure only (stage 2). The composer's renderer object gains these calls, which stage 4
implements in `report_composer.renderer_client.HttpRendererClient` (the real renderer's routes of
01-specs.md 16.3) and which this fake answers:

    renderer.block_types()                       GET  /v1/block-types  (items gain `description`,
                                                                        `new_instance_options`)
    renderer.fonts()                             GET  /v1/fonts        (unchanged)
    renderer.choices(project_id, system_id, t)   POST /v1/choices      (unchanged)
    renderer.coverage_choices(project_id, system_id)
        -> {objectives: [{value, label, group}], tests: [{value, label}], checklists: [{value, label}]}
                                                 POST /v1/coverage-choices (R-U2.7)
    renderer.render(snapshot)                    POST /v1/render
        preview -> {html, fingerprint, block_statuses}
        pdf     -> {pdf_base64, sha256, fingerprint, block_statuses}
        docx    -> {docx_base64, sha256, fingerprint, block_statuses}          (R-S.2, R-V8.9)

The block types are the shapes of 01-specs.md: every property carries `title` and `description`
(R-U5.1), enum values carry `x-aisc-enum-labels`, "more options" carry `x-aisc-more: true` (R-U5.4),
chart's dependent options carry `x-aisc-show-if` (R-V4.15), and the common properties include
`commentary` and `commentary_position` (R-V3.6). Part 2 (R2-D1.9): the renderer's `languages()` call is no
longer used by the composer, so the fake has none.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import time

import pytest

from conftest import BLOCK_TYPES, CHOICES, FONTS, IDS, PDF

FINGERPRINT = "f1a9e2b7c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789ab"
#: a DOCX is a zip; the fake's bytes start like one
DOCX = b"PK\x03\x04" + b"fake docx from the fake renderer" + b"\x00" * 16


def _p(schema: dict, title: str, description: str, more: bool = False, **extra) -> dict:
    out = {**schema, "title": title, "description": description, **extra}
    if more:
        out["x-aisc-more"] = True
    return out


COMMON_V2 = {
    "title": _p({"type": "string", "minLength": 0, "maxLength": 200}, "Section title",
                "Replaces the block's own heading.", more=True),
    "page_break_before": _p({"type": "boolean"}, "Start on a new page",
                            "Starts this section on a new page in the PDF.", more=True),
    "commentary": _p({"type": "string", "minLength": 0, "maxLength": 10000}, "Commentary",
                     "Your own words about this section, printed with it.", **{"x-aisc-prose": True}),
    "commentary_position": _p({"enum": ["after", "before"]}, "Place the commentary",
                              "Where the commentary goes.", more=True,
                              **{"x-aisc-enum-labels": {"after": "After the section", "before": "Before the section"}}),
}
COMMON_DEFAULTS = {"title": "", "page_break_before": False, "commentary": "", "commentary_position": "after"}

ALL_OR_LIST = {"oneOf": [{"const": "all"}, {"type": "array", "items": {"type": "string"}}]}
PAIR_LIST = {"oneOf": [{"const": "all"}, {"type": "array", "items": {
    "type": "object", "properties": {"tool": {"type": "string"}, "metric": {"type": "string"}}}}]}
REQUIREMENTS = ["R1 Human Agency and Oversight", "R2 Data Governance", "R3 Record Keeping", "R4 Accuracy",
                "R5 Transparency"]


def _type(type_id, title, props, defaults, required=(), description="", new_instance_options=None,
          contract_version=1, extra_schema=None):
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
              "properties": {**COMMON_V2, **props}, "additionalProperties": False}
    if required:
        schema["required"] = list(required)
    if extra_schema:
        schema.update(extra_schema)
    return {"type_id": type_id, "title": title, "contract_version": contract_version, "options_schema": schema,
            "default_options": {**COMMON_DEFAULTS, **defaults}, "description": description,
            "new_instance_options": new_instance_options or {}}


def _annotated(t: dict) -> dict:
    """A block type of 2026-09-23 with v2 annotations on every property (title, description)."""
    props = {}
    for name, prop in t["options_schema"]["properties"].items():
        if name in COMMON_V2:
            continue
        props[name] = _p(prop, name.replace("_", " ").capitalize() + " (label)", f"Help for {name}.")
    defaults = {k: v for k, v in t["default_options"].items() if k not in COMMON_DEFAULTS}
    return props, defaults


_BY = {t["type_id"]: t for t in BLOCK_TYPES}


def _v2_types() -> list[dict]:
    out = []
    # cover, ai_card, risk_classification, control_answers, dashboard_chart: annotated, main/more split (R-U5.4)
    for type_id, more in (("cover", {"show_logo", "show_generated_by"}), ("ai_card", {"show_graph_stats"}),
                          ("risk_classification", {"show_impact_areas"}), ("control_answers", {"include_archived"}),
                          ("dashboard_chart", {"include_replies", "width", "height"})):
        props, defaults = _annotated(_BY[type_id])
        for name in more:
            props[name]["x-aisc-more"] = True
        req = _BY[type_id]["options_schema"].get("required", ())
        out.append(_type(type_id, _BY[type_id]["title"], props, defaults, required=req,
                         description=f"The {_BY[type_id]['title']} block."))
    # control_objectives with the V6 filters
    props, defaults = _annotated(_BY["control_objectives"])
    props["group_by"]["x-aisc-enum-labels"] = {"objective": "By objective", "risk": "By risk"}
    for name in ("show_rationale", "show_quotes"):
        props[name]["x-aisc-more"] = True
    props.update({
        "requirements": _p({"oneOf": [{"const": "all"}, {"type": "array", "items": {"enum": REQUIREMENTS}}]},
                           "Requirement groups", "Only objectives of these groups."),
        "objectives": _p({**ALL_OR_LIST, "x-aisc-reference": True}, "Objectives", "Only these objectives.", more=True),
        "min_severity": _p({"type": ["integer", "null"], "minimum": 1, "maximum": 5}, "Lowest risk severity",
                           "Only objectives with a risk at least this severe."),
        "include_unrated": _p({"type": "boolean"}, "Include unrated risks", "Keeps risks with no severity.", more=True),
        "show_severity": _p({"type": "boolean"}, "Show severity", "Prints each risk's severity.", more=True),
    })
    defaults.update({"requirements": "all", "objectives": "all", "min_severity": None, "include_unrated": True,
                     "show_severity": False})
    out.append(_type("control_objectives", "Control objectives", props, defaults, contract_version=2,
                     description="The objectives mapped to the risks."))
    # test_results with metrics, detail, show_charts
    props, defaults = _annotated(_BY["test_results"])
    props["statuses"] = _p({"type": "array", "items": {"enum": ["Done", "Failed", "Running"]}}, "Run statuses",
                           "Only runs with these statuses.", more=True,
                           **{"x-aisc-enum-labels": {"Done": "Done", "Failed": "Failed", "Running": "Running"}})
    for name in ("show_measurements", "show_artifacts"):
        props[name]["x-aisc-more"] = True
    props.update({
        "metrics": _p({**PAIR_LIST, "x-aisc-reference": True}, "Metrics", "Only these metrics."),
        "detail": _p({"enum": ["full", "summary"]}, "Detail", "How much of each tool section is shown.",
                     **{"x-aisc-enum-labels": {"full": "Full", "summary": "Summary"}}),
        "show_charts": _p({"type": "boolean"}, "Show charts", "Draws the tools' charts.", more=True),
    })
    defaults.update({"metrics": "all", "detail": "full", "show_charts": True})
    out.append(_type("test_results", "Test results", props, defaults, contract_version=2,
                     description="The engine's test results."))
    # summary_coverage: legacy links stay, plus requirements
    props, defaults = _annotated(_BY["summary_coverage"])
    props["links"]["x-aisc-more"] = True
    props["requirements"] = _p({"oneOf": [{"const": "all"}, {"type": "array", "items": {"enum": REQUIREMENTS}}]},
                               "Requirement groups", "Only objectives of these groups.")
    defaults["requirements"] = "all"
    out.append(_type("summary_coverage", "Summary / coverage", props, defaults, contract_version=2,
                     description="Coverage of the objectives."))
    # free_text with format; new blocks get markdown (R-V3.12)
    out.append(_type("free_text", "Free text", {
        "text": _p({"type": "string", "minLength": 1, "maxLength": 20000}, "Text", "The section's text.",
                   **{"x-aisc-prose": True}),
        "format": _p({"enum": ["plain", "markdown"]}, "Format", "Plain text or light formatting.", more=True,
                     **{"x-aisc-enum-labels": {"plain": "Plain text", "markdown": "Light formatting"}}),
    }, {"format": "plain"}, required=("text",), contract_version=2, new_instance_options={"format": "markdown"},
        description="Your own text."))
    # new blocks: chart, key_figures, changes_since, chapter, appendix
    show = lambda *v: {"x-aisc-show-if": {"dataset": list(v)}}  # noqa: E731
    out.append(_type("chart", "Chart", {
        "dataset": _p({"enum": ["coverage_status", "checklist_scores", "tool_chart", "metric_by_evaluation",
                                "metric_by_dimension"]}, "Data", "What the chart shows.",
                      **{"x-aisc-enum-labels": {"coverage_status": "Coverage status", "checklist_scores": "Checklist scores",
                                                "tool_chart": "A tool's chart", "metric_by_evaluation": "A metric by evaluation",
                                                "metric_by_dimension": "A metric by dimension"}}),
        "tool_chart": _p({"type": "object", "properties": {"tool": {"type": "string"}, "chart": {"type": "string"}},
                          "x-aisc-reference": True}, "Tool chart", "Which tool chart.", **show("tool_chart")),
        "metric": _p({"type": "object", "properties": {"tool": {"type": "string"}, "metric": {"type": "string"}},
                      "x-aisc-reference": True}, "Metric", "Which metric.",
                     **show("metric_by_evaluation", "metric_by_dimension")),
        "dimension": _p({"type": "string", "x-aisc-prose": False}, "Dimension", "Group by this dimension.",
                        **show("metric_by_dimension")),
        "runs": _p({"enum": ["latest", "each"]}, "Runs", "The latest run or each run.", more=True,
                   **{"x-aisc-enum-labels": {"latest": "Latest run", "each": "Each run"}}),
        "show_table": _p({"type": "boolean"}, "Show the data table", "Prints the numbers under the chart.", more=True),
        "max_bars": _p({"type": "integer", "minimum": 3, "maximum": 40}, "Most bars", "At most this many bars.", more=True),
        "orientation": _p({"enum": ["auto", "vertical", "horizontal"]}, "Orientation", "Bar direction.", more=True,
                          **{"x-aisc-enum-labels": {"auto": "Automatic", "vertical": "Vertical", "horizontal": "Horizontal"}}),
    }, {"dataset": "coverage_status", "runs": "latest", "show_table": True, "max_bars": 20, "orientation": "auto"},
        description="A chart drawn in the report."))
    out.append(_type("key_figures", "Key figures", {
        "figures": _p({"type": "array", "items": {"enum": ["version", "risks", "objectives", "coverage", "tests",
                                                            "checklists"]}}, "Figures", "Which tiles to show.",
                      **{"x-aisc-enum-labels": {"version": "Version", "risks": "Risks", "objectives": "Objectives",
                                                "coverage": "Coverage", "tests": "Tests", "checklists": "Checklists"}}),
        "show_tool_headlines": _p({"type": "boolean"}, "Show tool headlines", "One tile per tool.", more=True),
    }, {"figures": ["version", "risks", "objectives", "coverage", "tests", "checklists"], "show_tool_headlines": True},
        description="The main numbers on one page."))
    out.append(_type("changes_since", "Changes since an earlier version", {
        "compare_to": _p({"type": "string", "x-aisc-reference": True}, "Compare with",
                         "The earlier version to compare with."),
        "sections": _p({"type": "array", "items": {"enum": ["card", "objectives", "tests", "controls"]}},
                       "Parts", "Which parts to compare.",
                       **{"x-aisc-enum-labels": {"card": "AI card", "objectives": "Objectives", "tests": "Tests",
                                                 "controls": "Controls"}}),
        "show_unchanged": _p({"type": "boolean"}, "Show unchanged", "Lists unchanged rows too.", more=True),
    }, {"compare_to": "previous", "sections": ["card", "objectives", "tests", "controls"], "show_unchanged": False},
        description="What changed since an earlier version."))
    chapter = _type("chapter", "Chapter", {
        "intro": _p({"type": "string", "maxLength": 5000}, "Introduction", "A short text under the heading.",
                    **{"x-aisc-prose": True}),
    }, {"intro": ""}, required=("title",), description="Groups the following blocks.")
    chapter["options_schema"]["properties"]["title"] = _p({"type": "string", "minLength": 1, "maxLength": 200},
                                                          "Chapter title", "The chapter's heading.")
    chapter["options_schema"]["properties"]["page_break_before"] = _p({"type": "boolean"}, "Start on a new page",
                                                                      "Starts the chapter on a new page.", more=True)
    chapter["default_options"].update({"title": "Chapter", "page_break_before": True})
    out.append(chapter)
    out.append(_type("appendix", "Appendix", {}, {}, description="Everything after it is the appendix."))
    return out


BLOCK_TYPES_V2 = _v2_types()
BY_TYPE_V2 = {t["type_id"]: t for t in BLOCK_TYPES_V2}

OBJECTIVES_A_V2 = [
    {"value": "R1.1", "label": "R1.1 Operator oversight capability", "group": "R1 Human Agency and Oversight"},
    {"value": "R2.1", "label": "R2.1 Training data quality", "group": "R2 Data Governance"},
    {"value": "R4.1", "label": "R4.1 Declared accuracy", "group": "R4 Accuracy"},
    {"value": "R5.1", "label": "R5.1 Instructions for use", "group": "R5 Transparency"},
]
COVERAGE_CHOICES = {
    IDS["A_V2"]: {"objectives": OBJECTIVES_A_V2,
                  "tests": [{"value": "LangBiTe", "label": "LangBiTe"}, {"value": "Mystery Tool", "label": "Mystery Tool"}],
                  "checklists": [{"value": "cl-1", "label": "Transparency checklist"},
                                 {"value": "cl-2", "label": "Oversight checklist"}]},
    # version 3 of Alpha has no objectives assessment
    IDS["A_V3"]: {"objectives": [], "tests": [{"value": "LangBiTe", "label": "LangBiTe"}], "checklists": []},
    IDS["A_V1"]: {"objectives": [{"value": "R3.1", "label": "R3.1 Automatic logs", "group": "R3 Record Keeping"}],
                  "tests": [{"value": "MLA-Reject", "label": "MLA-Reject"}, {"value": "LangBiTe", "label": "LangBiTe"}],
                  "checklists": [{"value": "cl-1", "label": "Transparency checklist"}]},
    # Gamma: objectives but no test results and no checklists
    IDS["C_V1"]: {"objectives": [{"value": "R1.1", "label": "R1.1 Operator oversight capability",
                                  "group": "R1 Human Agency and Oversight"}], "tests": [], "checklists": []},
}

METRICS_A_V2 = [{"value": {"tool": "LangBiTe", "metric": "bias_rate"}, "label": "LangBiTe: bias_rate"},
                {"value": {"tool": "Mystery Tool", "metric": "mystery_metric"}, "label": "Mystery Tool: mystery_metric"}]
CHOICES_V2 = copy.deepcopy(CHOICES)
CHOICES_V2[(IDS["A_V2"], "test_results")]["metrics"] = METRICS_A_V2
CHOICES_V2.update({
    (IDS["A_V2"], "control_objectives"): {"objectives": [{"value": o["value"], "label": o["label"]}
                                                          for o in OBJECTIVES_A_V2]},
    (IDS["A_V2"], "chart"): {"tool_chart": [{"value": {"tool": "LangBiTe", "chart": "pass_rate_by_concern"},
                                             "label": "LangBiTe: Pass rate by concern"}],
                             "metric": METRICS_A_V2},
    (IDS["A_V2"], "changes_since"): {"compare_to": [{"value": IDS["A_V1"], "label": "Version 1 (0.9)"}]},
    (IDS["A_V3"], "changes_since"): {"compare_to": [{"value": IDS["A_V2"], "label": "Version 2 (1.0)"},
                                                    {"value": IDS["A_V1"], "label": "Version 1 (0.9)"}]},
    (IDS["A_V1"], "changes_since"): {"compare_to": []},
})


class FakeRendererV2:
    """The v2 renderer from the composer's side (R7.4.1 still holds: the composer tests need no renderer)."""

    def __init__(self):
        self.snapshots = []
        self.choice_calls = []
        self.coverage_calls = []
        self.fail = None
        self.error_blocks = set()
        self.pdf = PDF
        self.docx = DOCX
        self.fingerprint = FINGERPRINT

    def block_types(self):
        return copy.deepcopy(BLOCK_TYPES_V2)

    def fonts(self):
        return copy.deepcopy(FONTS)

    def choices(self, project_id, system_id, block_type):
        self.choice_calls.append((str(project_id), str(system_id), block_type))
        return copy.deepcopy(CHOICES_V2.get((str(system_id), block_type), {}))

    def coverage_choices(self, project_id, system_id):
        self.coverage_calls.append((str(project_id), str(system_id)))
        return copy.deepcopy(COVERAGE_CHOICES.get(str(system_id), {"objectives": [], "tests": [], "checklists": []}))

    def render(self, snapshot):
        self.snapshots.append(copy.deepcopy(snapshot))
        if self.fail:
            raise self.fail
        known = set(BY_TYPE_V2)
        statuses = [{"instance_id": b["instance_id"], "block_type": b["block_type"],
                     "status": "error" if (b["instance_id"] in self.error_blocks or b["block_type"] not in known) else "ok",
                     "notices": []} for b in snapshot["blocks"]]
        mode = snapshot["mode"]
        if mode == "preview":
            lang = snapshot.get("language", "en")
            html = (f'<!DOCTYPE html><html lang="{lang}"><head><meta charset="utf-8"><title>Preview</title></head><body>'
                    + "".join(f'<section id="block-{b["instance_id"]}">{b["block_type"]}</section>'
                              for b in snapshot["blocks"]) + "</body></html>")
            return {"html": html, "fingerprint": self.fingerprint, "block_statuses": statuses}
        data = self.docx if mode == "docx" else self.pdf
        key = "docx_base64" if mode == "docx" else "pdf_base64"
        return {key: base64.b64encode(data).decode(), "sha256": hashlib.sha256(data).hexdigest(),
                "fingerprint": self.fingerprint, "block_statuses": statuses}


@pytest.fixture
def fake_v2():
    return FakeRendererV2()


@pytest.fixture
def client_v2(make_client, fake_v2):
    return make_client(fake_v2)


@pytest.fixture
def clean_presets(bed):
    """Saved presets are platform wide: every test starts without any (the table may not exist yet)."""
    bed.psql("platform", "DO $$ BEGIN IF to_regclass('report_composer.preset') IS NOT NULL THEN "
                         "DELETE FROM report_composer.preset; END IF; END $$;", check=False)
    yield


def unique(prefix: str) -> str:
    return f"{prefix} {time.monotonic_ns()}"


def scalar_json(bed, sql: str):
    """One JSON value from the bed (bed.rows() cannot parse psql's footer, see 05-report F1)."""
    import json

    out = bed.scalar("platform", sql)
    return json.loads(out) if out not in (None, "") else None


def v2blk(block_type, **options):
    import uuid

    return {"instance_id": str(uuid.uuid4()), "block_type": block_type, "options": options}
