"""The two rule sets a project can start from: one person throughout, and four eyes."""
from __future__ import annotations

from platform_service.work import presets
from platform_service.work.kinds import KINDS, LABELS


def test_the_kinds_of_task_are_the_thirteen_of_the_spec_in_its_order():
    assert KINDS == ("describe_system", "correct_card", "name_system", "choose_objectives", "rate_risks",
                     "choose_tests", "fill_checklist", "amend_checklist", "launch_run", "review_results",
                     "map_evidence", "compose_report", "release_report")


def test_every_kind_has_a_label_for_pages_and_reports():
    assert set(LABELS) == set(KINDS)
    assert all(label and label[0].isupper() for label in LABELS.values())


def test_the_presets_are_light_and_four_eyes():
    assert presets.NAMES == ("light", "four_eyes")
