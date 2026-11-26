"""What a staffing rule may say: how many people do a task and the check stages after it.

The number of people is a setting, so the shape has to admit one person with no check as readily as a
committee, and refuse only what cannot be carried out or would let the doer choose their own control.
"""
from __future__ import annotations

import pytest

from platform_service.work import staffing
from platform_service.work.staffing import InvalidRule
from tests.staffing_rules import ANY, functions, people, rule, stage

KNOWN = {"system_owner": 1, "developer": 1, "risk": 2, "compliance": 2, "audit": 3}


def validate(r):
    return staffing.validate(r, functions=KNOWN)


def refused_at(r):
    with pytest.raises(InvalidRule) as caught:
        validate(r)
    return caught.value.pointer


def test_one_person_and_no_check_is_a_valid_rule():
    assert validate(rule())["stages"] == []


def test_an_empty_rule_gets_the_defaults():
    assert validate({}) == rule()


def test_a_stage_given_only_its_number_gets_the_defaults():
    assert validate({"stages": [{"needed": 2}]})["stages"] == [stage(needed=2)]


def test_four_eyes_is_one_stage_of_one():
    assert len(validate(rule(stage()))["stages"]) == 1


def test_a_committee_is_some_of_the_people_named():
    r = rule(stage(needed=2, group=people("a", "b", "c", "d", "e")))
    assert validate(r)["stages"][0]["needed"] == 2


def test_four_stages_are_accepted():
    assert len(validate(rule(stage(), stage(), stage(), stage()))["stages"]) == 4


def test_a_fifth_stage_is_refused():
    assert refused_at(rule(stage(), stage(), stage(), stage(), stage())) == "/stages"


def test_a_stage_needs_at_least_one_person():
    assert refused_at(rule(stage(needed=0))) == "/stages/0/needed"


def test_a_stage_cannot_need_more_than_twenty():
    assert refused_at(rule(stage(needed=21))) == "/stages/0/needed"


def test_a_stage_cannot_need_more_people_than_it_names():
    assert refused_at(rule(stage(needed=3, group=people("a", "b")))) == "/stages/0/needed"


def test_a_task_has_at_least_one_doer():
    assert refused_at(rule(count=0)) == "/doers/count"


def test_a_doer_mode_is_one_of_the_two():
    assert refused_at(rule(mode="most")) == "/doers/mode"


def test_a_stage_kind_is_review_or_approval():
    assert refused_at(rule(stage(kind="visa"))) == "/stages/0/kind"


def test_a_function_named_in_a_stage_must_exist_for_the_project():
    assert refused_at(rule(stage(group=functions("actuarial")))) == "/stages/0/from/functions/0"


def test_a_function_named_for_the_doers_must_exist_for_the_project():
    assert refused_at(rule(doers_from=functions("actuarial"))) == "/doers/from/functions/0"


def test_audit_can_never_be_named_as_a_checker():
    assert refused_at(rule(stage(group=functions("risk", "audit")))) == "/stages/0/from/functions/1"


def test_audit_can_never_be_named_as_a_doer():
    assert refused_at(rule(doers_from=functions("audit"))) == "/doers/from/functions/0"


def test_a_group_of_functions_names_at_least_one():
    assert refused_at(rule(stage(group=functions()))) == "/stages/0/from/functions"


def test_due_days_are_between_one_and_sixty():
    assert refused_at(rule(stage(due_days=0))) == "/stages/0/due_days"
    assert refused_at(rule(stage(due_days=61))) == "/stages/0/due_days"


def test_a_rule_sampled_one_in_five_is_valid():
    assert validate(rule(stage(), sampled={"one_in": 5}))["sampled"] == {"one_in": 5}


def test_sampling_one_in_one_is_refused_because_it_is_every_task():
    assert refused_at(rule(stage(), sampled={"one_in": 1})) == "/sampled/one_in"


def test_sampling_above_one_in_a_hundred_is_refused():
    assert refused_at(rule(stage(), sampled={"one_in": 101})) == "/sampled/one_in"


def test_sampling_without_a_stage_is_refused_because_there_is_nothing_to_sample():
    assert refused_at(rule(sampled={"one_in": 5})) == "/sampled"


def test_a_rule_sampled_by_condition_is_valid():
    r = rule(stage(), sampled={"when": ["test_failed", "doer_asked"]})
    assert validate(r)["sampled"] == {"when": ["test_failed", "doer_asked"]}


def test_an_unknown_sampling_condition_is_refused():
    assert refused_at(rule(stage(), sampled={"when": ["on_fridays"]})) == "/sampled/when/0"


def test_the_doer_asking_cannot_be_the_only_condition_for_a_check():
    assert refused_at(rule(stage(), sampled={"when": ["doer_asked"]})) == "/sampled/when"


def test_a_setting_the_rule_does_not_have_is_refused():
    r = rule(stage())
    r["stages"][0]["signer_may_be_doer"] = True
    assert refused_at(r) == "/stages/0/signer_may_be_doer"


def test_a_refusal_says_what_is_wrong_in_words():
    with pytest.raises(InvalidRule) as caught:
        validate(rule(stage(needed=0)))
    assert "at least 1" in caught.value.message


def test_validating_does_not_change_the_rule_it_was_given():
    given = {"stages": [{"needed": 2}]}
    validate(given)
    assert given == {"stages": [{"needed": 2}]}
