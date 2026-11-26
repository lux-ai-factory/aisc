"""Which changes of a staffing rule lower control.

A loosening waits for a second person, a tightening applies at once, so the difference has to be
decided setting by setting and never by an overall impression.
"""
from __future__ import annotations

from platform_service.work import staffing
from tests.staffing_rules import ANY, functions, people, rule, stage


def reasons(before, after):
    return staffing.is_loosening(before, after)


def test_the_same_rule_is_not_a_loosening():
    assert reasons(rule(stage()), rule(stage())) == []


def test_removing_a_stage_is_a_loosening():
    assert reasons(rule(stage(), stage()), rule(stage())) == ["fewer_stages"]


def test_removing_the_only_check_is_a_loosening():
    assert reasons(rule(stage()), rule()) == ["fewer_stages"]


def test_adding_a_stage_is_not():
    assert reasons(rule(stage()), rule(stage(), stage())) == []


def test_a_stage_that_needs_fewer_people_is_a_loosening():
    assert reasons(rule(stage(needed=2)), rule(stage(needed=1))) == ["fewer_needed"]


def test_a_stage_that_needs_more_people_is_not():
    assert reasons(rule(stage(needed=1)), rule(stage(needed=2))) == []


def test_from_a_function_to_any_member_is_a_wider_group():
    assert reasons(rule(stage(group=functions("risk"))), rule(stage(group=ANY))) == ["wider_group"]


def test_from_named_people_to_a_function_is_a_wider_group():
    assert reasons(rule(stage(group=people("a"))), rule(stage(group=functions("risk")))) == ["wider_group"]


def test_one_more_function_is_a_wider_group():
    before, after = rule(stage(group=functions("risk"))), rule(stage(group=functions("risk", "compliance")))
    assert reasons(before, after) == ["wider_group"]


def test_one_more_named_person_is_a_wider_group():
    assert reasons(rule(stage(group=people("a"))), rule(stage(group=people("a", "b")))) == ["wider_group"]


def test_other_people_of_the_same_number_are_a_wider_group_because_someone_new_may_sign():
    assert reasons(rule(stage(group=people("a"))), rule(stage(group=people("b")))) == ["wider_group"]


def test_from_any_member_to_a_function_is_not_a_loosening():
    assert reasons(rule(stage(group=ANY)), rule(stage(group=functions("risk")))) == []


def test_fewer_functions_is_not_a_loosening():
    before, after = rule(stage(group=functions("risk", "compliance"))), rule(stage(group=functions("risk")))
    assert reasons(before, after) == []


def test_switching_off_the_other_line_setting_is_a_loosening():
    assert reasons(rule(stage(other_line=True)), rule(stage(other_line=False))) == ["weaker_independence"]


def test_switching_off_not_an_earlier_signer_is_a_loosening():
    before = rule(stage(), stage(not_earlier_signer=True))
    assert reasons(before, rule(stage(), stage())) == ["weaker_independence"]


def test_letting_a_stage_pass_over_an_objection_is_a_loosening():
    after = rule(stage(needed=2, any_objection_sends_back=False))
    assert reasons(rule(stage(needed=2)), after) == ["weaker_independence"]


def test_switching_an_independence_setting_on_is_not():
    assert reasons(rule(stage()), rule(stage(other_line=True))) == []


def test_an_approval_that_becomes_a_review_is_a_loosening():
    assert reasons(rule(stage(kind="approval")), rule(stage(kind="review"))) == ["approval_to_review"]


def test_a_review_that_becomes_an_approval_is_not():
    assert reasons(rule(stage(kind="review")), rule(stage(kind="approval"))) == []


def test_starting_to_sample_is_a_loosening():
    assert reasons(rule(stage()), rule(stage(), sampled={"one_in": 5})) == ["more_sampling"]


def test_sampling_fewer_tasks_is_a_loosening():
    before, after = rule(stage(), sampled={"one_in": 5}), rule(stage(), sampled={"one_in": 10})
    assert reasons(before, after) == ["more_sampling"]


def test_sampling_more_tasks_is_not():
    before, after = rule(stage(), sampled={"one_in": 10}), rule(stage(), sampled={"one_in": 5})
    assert reasons(before, after) == []


def test_checking_every_task_again_is_not():
    assert reasons(rule(stage(), sampled={"one_in": 5}), rule(stage())) == []


def test_dropping_a_condition_for_a_check_is_a_loosening():
    before = rule(stage(), sampled={"when": ["test_failed", "risk_above_3"]})
    assert reasons(before, rule(stage(), sampled={"when": ["test_failed"]})) == ["more_sampling"]


def test_from_a_draw_to_conditions_is_a_loosening():
    before, after = rule(stage(), sampled={"one_in": 5}), rule(stage(), sampled={"when": ["test_failed"]})
    assert reasons(before, after) == ["more_sampling"]


def test_changing_who_does_the_work_is_never_a_loosening():
    assert reasons(rule(stage(), count=2, mode="all"), rule(stage(), count=1)) == []


def test_changing_due_days_is_never_a_loosening():
    assert reasons(rule(stage(due_days=3)), rule(stage(due_days=30))) == []


def test_a_change_that_tightens_one_setting_and_loosens_another_is_a_loosening():
    before = rule(stage(needed=1, group=functions("risk")))
    after = rule(stage(needed=2, group=ANY))
    assert reasons(before, after) == ["wider_group"]


def test_each_reason_is_given_once_however_many_stages_show_it():
    before = rule(stage(needed=2), stage(needed=2))
    assert reasons(before, rule(stage(needed=1), stage(needed=1))) == ["fewer_needed"]


def test_several_reasons_come_in_the_order_the_spec_lists_them():
    before = rule(stage(needed=2, kind="approval", other_line=True), stage())
    after = rule(stage(needed=1, kind="review"), sampled={"one_in": 5})
    assert reasons(before, after) == ["fewer_stages", "fewer_needed", "weaker_independence",
                                      "approval_to_review", "more_sampling"]


def test_a_lower_tier_is_a_loosening():
    assert staffing.tier_change("high", "medium") == ["lower_tier"]


def test_a_higher_tier_is_not():
    assert staffing.tier_change("low", "high") == []


def test_the_same_tier_is_not():
    assert staffing.tier_change("medium", "medium") == []
