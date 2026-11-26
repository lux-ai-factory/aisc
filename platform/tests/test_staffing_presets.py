"""The two rule sets a project can start from: one person throughout, and four eyes."""
from __future__ import annotations

import pytest

from platform_service.work import presets, staffing
from platform_service.work.kinds import KINDS, LABELS, TIERS
from tests.staffing_rules import ANY, rule, stage

FUNCTIONS = {"system_owner": 1, "risk": 2, "audit": 3}
WITHOUT_A_CHECK_IN_FOUR_EYES = {"launch_run", "compose_report"}


def test_the_kinds_of_task_are_the_thirteen_of_the_spec_in_its_order():
    assert KINDS == ("describe_system", "correct_card", "name_system", "choose_objectives", "rate_risks",
                     "choose_tests", "fill_checklist", "amend_checklist", "launch_run", "review_results",
                     "map_evidence", "compose_report", "release_report")


def test_every_kind_has_a_label_for_pages_and_reports():
    assert set(LABELS) == set(KINDS)
    assert all(label and label[0].isupper() for label in LABELS.values())


def test_the_tiers_are_low_medium_high_in_that_order():
    assert TIERS == ("low", "medium", "high")


def test_the_presets_are_light_and_four_eyes():
    assert presets.NAMES == ("light", "four_eyes")


@pytest.mark.parametrize("name", ["light", "four_eyes"])
def test_a_preset_has_a_valid_rule_for_every_kind_and_tier(name):
    for kind in KINDS:
        for tier in TIERS:
            r = presets.rule(name, kind, tier)
            assert staffing.validate(r, functions=FUNCTIONS) == r, f"{name} {kind} {tier}"


def test_light_is_one_person_and_no_check_for_every_kind():
    for kind in KINDS:
        for tier in TIERS:
            assert presets.rule("light", kind, tier) == rule(), f"{kind} {tier}"


def test_four_eyes_is_one_check_by_any_member_on_every_judgement():
    for kind in set(KINDS) - WITHOUT_A_CHECK_IN_FOUR_EYES:
        for tier in TIERS:
            assert presets.rule("four_eyes", kind, tier) == rule(stage(needed=1, group=ANY, kind="review")), kind


def test_four_eyes_leaves_launching_a_run_and_composing_a_report_to_one_person():
    for kind in WITHOUT_A_CHECK_IN_FOUR_EYES:
        for tier in TIERS:
            assert presets.rule("four_eyes", kind, tier) == rule(), kind


def test_an_unknown_preset_is_an_error_not_a_default():
    with pytest.raises(KeyError):
        presets.rule("bank", "describe_system", "high")


def test_going_from_light_to_four_eyes_loosens_nothing():
    for kind in KINDS:
        before, after = presets.rule("light", kind, "medium"), presets.rule("four_eyes", kind, "medium")
        assert staffing.is_loosening(before, after) == [], kind


def test_going_from_four_eyes_to_light_loosens_every_kind_that_had_a_check():
    for kind in set(KINDS) - WITHOUT_A_CHECK_IN_FOUR_EYES:
        before, after = presets.rule("four_eyes", kind, "medium"), presets.rule("light", kind, "medium")
        assert staffing.is_loosening(before, after) == ["fewer_stages"], kind
