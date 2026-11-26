"""Who may change a project's controls, and when a change waits for a second person.

The owner of a project is usually one of the people whose work the rules are about. So a change that
lowers control never rests on one person: it is proposed with a reason and confirmed by someone else.
"""
from __future__ import annotations

from platform_service.work import controls

ANNA, LUCA, MARC = "anna", "luca", "marc"


def decide(what="rule", loosening=(), reason="", *, actor=ANNA, role="owner", is_admin=False):
    return controls.decide(actor_subject=actor, actor_role=role, actor_is_admin=is_admin, what=what,
                           loosening=list(loosening), reason=reason)


def test_an_owner_tightens_a_rule_at_once():
    assert decide("rule") == "allowed"


def test_an_owner_who_loosens_a_rule_needs_a_second_person():
    assert decide("rule", ["fewer_stages"], "the team shrank to two") == "needs_second_person"


def test_a_loosening_without_a_reason_is_refused():
    assert decide("rule", ["fewer_stages"], "") == "reason_required"
    assert decide("rule", ["fewer_stages"], "   ") == "reason_required"


def test_a_tightening_needs_no_reason():
    assert decide("tier", [], "") == "allowed"


def test_an_editor_cannot_change_a_rule():
    assert decide("rule", role="editor") == "owner_only"


def test_a_viewer_cannot_change_the_tier():
    assert decide("tier", role="viewer") == "owner_only"


def test_someone_outside_the_project_cannot_change_a_function():
    assert decide("function", role=None) == "owner_only"


def test_the_admin_changes_a_rule_without_being_a_member():
    assert decide("rule", actor=MARC, role=None, is_admin=True) == "allowed"


def test_the_admin_who_loosens_needs_a_second_person_like_anyone():
    assert decide("tier", ["lower_tier"], "pilot only", actor=MARC, role=None,
                  is_admin=True) == "needs_second_person"


def test_only_the_admin_changes_the_floor():
    assert decide("floor", role="owner") == "admin_only"
    assert decide("floor", actor=MARC, role=None, is_admin=True) == "allowed"


def test_lowering_the_floor_needs_a_second_person_too():
    assert decide("floor", ["lower_floor"], "one-person teams", actor=MARC, role=None,
                  is_admin=True) == "needs_second_person"


def test_giving_someone_a_checking_function_needs_a_second_person():
    assert decide("function", ["checker_added"], "Luca joins risk") == "needs_second_person"


def test_an_unknown_kind_of_change_is_an_error():
    import pytest

    with pytest.raises(ValueError):
        decide("budget")


def confirm(*, actor=LUCA, role="owner", is_admin=False, proposed_by=ANNA, what="rule"):
    return controls.may_confirm(actor_subject=actor, actor_role=role, actor_is_admin=is_admin,
                                proposed_by=proposed_by, what=what)


def test_another_owner_confirms_a_loosening():
    assert confirm() is None


def test_the_person_who_proposed_it_cannot_confirm_it():
    assert confirm(actor=ANNA) == "same_person"


def test_the_admin_confirms_an_owners_loosening():
    assert confirm(actor=MARC, role=None, is_admin=True) is None


def test_the_admin_cannot_confirm_what_the_admin_proposed():
    assert confirm(actor=MARC, role=None, is_admin=True, proposed_by=MARC) == "same_person"


def test_an_editor_cannot_confirm():
    assert confirm(role="editor") == "owner_only"


def test_a_lower_floor_is_confirmed_by_another_admin_only():
    assert confirm(what="floor", role="owner") == "admin_only"
    assert confirm(what="floor", actor=LUCA, role=None, is_admin=True, proposed_by=MARC) is None


def test_rejecting_follows_the_same_rule_as_confirming_except_that_the_proposer_may_withdraw():
    assert controls.may_reject(actor_subject=ANNA, actor_role="owner", actor_is_admin=False,
                               proposed_by=ANNA, what="rule") is None
    assert controls.may_reject(actor_subject=LUCA, actor_role="editor", actor_is_admin=False,
                               proposed_by=ANNA, what="rule") == "owner_only"


def test_an_admin_who_is_not_a_member_is_recorded_as_acting_as_admin():
    assert controls.acted_as(actor_role=None, actor_is_admin=True) == "admin"


def test_an_admin_who_is_an_owner_of_the_project_acts_as_owner():
    assert controls.acted_as(actor_role="owner", actor_is_admin=True) == "owner"


def test_an_owner_acts_as_owner():
    assert controls.acted_as(actor_role="owner", actor_is_admin=False) == "owner"
