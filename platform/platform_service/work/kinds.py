"""The kinds of work a project has.

A task is an instance of one of these kinds. The order is the order of the steps, and pages and reports
list kinds in it.
"""
from __future__ import annotations

KINDS = ("describe_system", "correct_card", "name_system", "choose_objectives", "rate_risks", "choose_tests",
         "fill_checklist", "amend_checklist", "launch_run", "review_results", "map_evidence", "compose_report",
         "release_report")

LABELS = {
    "describe_system": "Describe the system",
    "correct_card": "Correct the card",
    "name_system": "Name the system under assessment",
    "choose_objectives": "Choose objectives",
    "rate_risks": "Rate and map the risks",
    "choose_tests": "Choose the tests and checklists",
    "fill_checklist": "Fill a checklist",
    "amend_checklist": "Amend a checklist",
    "launch_run": "Configure and launch a run",
    "review_results": "Review the results",
    "map_evidence": "Map the evidence",
    "compose_report": "Compose the report",
    "release_report": "Release the report",
}
