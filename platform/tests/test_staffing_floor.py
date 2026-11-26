"""The floor: what every staffing rule of an installation must at least ask for.

A project is free to choose its numbers, down to one person and no check, unless the installation
says otherwise. The floor is where it says so, and a rule is measured against it setting by setting.
"""
from __future__ import annotations

from platform_service.work import staffing
from tests.staffing_rules import ANY, floor, functions, people, rule, stage


def missing(r, f):
    return staffing.meets_floor(r, f)


def test_without_a_floor_one_person_and_no_check_is_allowed():
    assert missing(rule(), None) == []


def test_a_floor_that_asks_for_nothing_is_met_by_every_rule():
    assert missing(rule(), floor()) == []


def test_a_rule_with_fewer_stages_than_the_floor_fails_it():
    assert missing(rule(), floor(min_stages=1)) == ["too_few_stages"]


def test_a_rule_with_as_many_stages_as_the_floor_meets_it():
    assert missing(rule(stage()), floor(min_stages=1)) == []


def test_a_sampled_rule_counts_as_having_no_stage():
    assert missing(rule(stage(), sampled={"one_in": 5}), floor(min_stages=1)) == ["too_few_stages"]


def test_a_rule_checked_only_on_a_condition_counts_as_having_no_stage():
    r = rule(stage(), sampled={"when": ["test_failed"]})
    assert missing(r, floor(min_stages=1)) == ["too_few_stages"]


def test_a_sampled_rule_meets_the_stage_count_when_the_floor_allows_that_much_sampling():
    r = rule(stage(), sampled={"one_in": 5})
    assert missing(r, floor(min_stages=1, sampling={"max_one_in": 5})) == []


def test_a_stage_that_needs_fewer_people_than_the_floor_fails_it():
    assert missing(rule(stage(needed=1)), floor(min_stages=1, min_needed=2)) == ["too_few_needed"]


def test_every_stage_has_to_meet_the_number_not_only_the_first():
    r = rule(stage(needed=2), stage(needed=1))
    assert missing(r, floor(min_needed=2)) == ["too_few_needed"]


def test_a_floor_can_require_a_checker_from_another_line():
    assert missing(rule(stage()), floor(require_other_line=True)) == ["other_line_required"]
    assert missing(rule(stage(other_line=True)), floor(require_other_line=True)) == []


def test_a_floor_can_require_that_later_stages_are_signed_by_someone_new():
    f = floor(require_not_earlier_signer=True)
    assert missing(rule(stage(), stage()), f) == ["not_earlier_signer_required"]
    assert missing(rule(stage(), stage(not_earlier_signer=True)), f) == []


def test_the_first_stage_has_no_earlier_signer_to_exclude():
    assert missing(rule(stage()), floor(require_not_earlier_signer=True)) == []


def test_a_floor_can_name_the_functions_a_check_may_come_from():
    f = floor(allowed_from=["risk", "compliance"])
    assert missing(rule(stage(group=functions("risk"))), f) == []
    assert missing(rule(stage(group=functions("risk", "legal"))), f) == ["group_not_allowed"]


def test_any_member_is_not_one_of_the_functions_a_floor_names():
    assert missing(rule(stage(group=ANY)), floor(allowed_from=["risk"])) == ["group_not_allowed"]


def test_named_people_are_not_one_of_the_functions_a_floor_names():
    assert missing(rule(stage(group=people("a"))), floor(allowed_from=["risk"])) == ["group_not_allowed"]


def test_a_floor_can_forbid_sampling():
    r = rule(stage(), sampled={"one_in": 5})
    assert missing(r, floor(sampling="never")) == ["sampling_not_allowed"]


def test_a_floor_can_limit_how_thin_the_sample_is():
    f = floor(sampling={"max_one_in": 5})
    assert missing(rule(stage(), sampled={"one_in": 5}), f) == []
    assert missing(rule(stage(), sampled={"one_in": 6}), f) == ["sampling_not_allowed"]


def test_checks_on_a_condition_are_not_allowed_where_the_sample_is_limited():
    r = rule(stage(), sampled={"when": ["test_failed"]})
    assert missing(r, floor(sampling={"max_one_in": 5})) == ["sampling_not_allowed"]


def test_a_floor_without_a_word_on_sampling_allows_it():
    assert missing(rule(stage(), sampled={"one_in": 50}), floor(sampling=None)) == []


def test_everything_missing_is_listed_in_the_order_of_the_spec():
    f = floor(min_stages=2, min_needed=2, require_other_line=True, allowed_from=["risk"], sampling="never")
    r = rule(stage(), sampled={"one_in": 5})
    assert missing(r, f) == ["too_few_stages", "too_few_needed", "other_line_required", "group_not_allowed",
                             "sampling_not_allowed"]


def test_the_floor_in_force_is_the_stricter_of_the_tiers_own_and_the_one_for_every_tier():
    for_tier = floor(min_stages=1, min_needed=1, sampling={"max_one_in": 10})
    for_every_tier = floor(min_stages=0, min_needed=2, require_other_line=True, sampling={"max_one_in": 5})
    assert staffing.combine_floors(for_tier, for_every_tier) == floor(
        min_stages=1, min_needed=2, require_other_line=True, sampling={"max_one_in": 5})


def test_never_sampling_is_stricter_than_any_limit():
    combined = staffing.combine_floors(floor(sampling={"max_one_in": 5}), floor(sampling="never"))
    assert combined["sampling"] == "never"


def test_a_limit_is_stricter_than_no_word_on_sampling():
    combined = staffing.combine_floors(floor(sampling=None), floor(sampling={"max_one_in": 5}))
    assert combined["sampling"] == {"max_one_in": 5}


def test_two_lists_of_allowed_functions_combine_to_what_both_allow():
    combined = staffing.combine_floors(floor(allowed_from=["risk", "compliance"]), floor(allowed_from=["risk"]))
    assert combined["allowed_from"] == ["risk"]


def test_one_missing_floor_leaves_the_other():
    assert staffing.combine_floors(None, floor(min_stages=1)) == floor(min_stages=1)
    assert staffing.combine_floors(None, None) is None


def test_a_floor_that_asks_for_less_than_before_is_lower():
    assert staffing.is_lower_floor(floor(min_stages=1), floor(min_stages=0)) is True


def test_a_floor_that_starts_to_allow_sampling_is_lower():
    assert staffing.is_lower_floor(floor(sampling="never"), floor(sampling={"max_one_in": 5})) is True


def test_a_floor_that_asks_for_more_is_not_lower():
    assert staffing.is_lower_floor(floor(min_stages=1), floor(min_stages=2, min_needed=2)) is False


def test_removing_a_floor_is_lower_and_setting_the_first_one_is_not():
    assert staffing.is_lower_floor(floor(min_stages=1), None) is True
    assert staffing.is_lower_floor(None, floor(min_stages=1)) is False
