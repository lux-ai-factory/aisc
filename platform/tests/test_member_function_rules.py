"""Who may hold which function in a project, and who may give it.

A function decides whose work a member may check, so the rules about functions are part of the
control: nobody gives one to themselves, nobody stands in two lines, and audit stands apart.
"""
from __future__ import annotations

from platform_service.work import functions

CATALOGUE = {"system_owner": 1, "developer": 1, "tester": 1, "risk": 2, "compliance": 2, "legal": 2,
             "audit": 3}
ANNA, LUCA, MARC = "anna", "luca", "marc"


def grant(function, *, held=(), member=LUCA, member_role="editor", actor=ANNA, actor_role="owner",
          actor_is_admin=False):
    return functions.grant_allowed(actor_subject=actor, actor_role=actor_role, actor_is_admin=actor_is_admin,
                                   member_subject=member, member_role=member_role, held=list(held),
                                   function=function, catalogue=CATALOGUE)


def test_an_owner_gives_a_member_a_function():
    assert grant("risk") is None


def test_an_editor_cannot_give_a_function():
    assert grant("risk", actor_role="editor") == "owner_only"


def test_the_platform_admin_can_give_a_function_without_being_an_owner():
    assert grant("risk", actor=MARC, actor_role=None, actor_is_admin=True) is None


def test_nobody_gives_a_function_to_themselves_not_even_an_owner():
    assert grant("risk", member=ANNA, member_role="owner") == "own_functions"


def test_nobody_gives_a_function_to_themselves_not_even_the_admin():
    assert grant("risk", actor=MARC, actor_role="owner", actor_is_admin=True, member=MARC,
                 member_role="owner") == "own_functions"


def test_a_function_the_project_does_not_have_is_refused():
    assert grant("actuarial") == "unknown_function"


def test_a_second_function_of_the_same_line_is_allowed():
    assert grant("compliance", held=["risk"]) is None


def test_a_function_of_another_line_is_refused():
    assert grant("risk", held=["developer"]) == "mixed_lines"


def test_a_first_line_function_is_refused_for_someone_in_the_second_line():
    assert grant("tester", held=["risk", "legal"]) == "mixed_lines"


def test_audit_is_given_to_a_viewer_who_holds_nothing_else():
    assert grant("audit", member_role="viewer") is None


def test_audit_is_not_given_to_someone_who_holds_another_function():
    assert grant("audit", held=["risk"], member_role="viewer") == "audit_alone"


def test_nothing_else_is_given_to_someone_who_holds_audit():
    assert grant("risk", held=["audit"], member_role="viewer") == "audit_alone"


def test_audit_is_not_given_to_an_editor():
    assert grant("audit", member_role="editor") == "audit_viewer_only"


def test_audit_is_not_given_to_an_owner():
    assert grant("audit", member_role="owner") == "audit_viewer_only"


def test_giving_a_function_already_held_is_allowed_and_changes_nothing():
    assert grant("risk", held=["risk"]) is None


def remove(*, member=LUCA, actor=ANNA, actor_role="owner", actor_is_admin=False):
    return functions.removal_allowed(actor_subject=actor, actor_role=actor_role,
                                     actor_is_admin=actor_is_admin, member_subject=member)


def test_an_owner_takes_a_function_away():
    assert remove() is None


def test_an_editor_cannot_take_a_function_away():
    assert remove(actor_role="editor") == "owner_only"


def test_nobody_takes_away_their_own_function():
    assert remove(member=ANNA) == "own_functions"


def test_someone_who_holds_audit_cannot_be_made_an_editor():
    assert functions.role_change_allowed(held=["audit"], new_role="editor") == "audit_viewer_only"


def test_someone_who_holds_audit_cannot_be_made_an_owner():
    assert functions.role_change_allowed(held=["audit"], new_role="owner") == "audit_viewer_only"


def test_someone_who_holds_audit_can_stay_a_viewer():
    assert functions.role_change_allowed(held=["audit"], new_role="viewer") is None


def test_a_role_change_of_anyone_else_is_not_the_business_of_functions():
    assert functions.role_change_allowed(held=["risk"], new_role="owner") is None
    assert functions.role_change_allowed(held=[], new_role="editor") is None


def test_giving_a_second_line_function_adds_a_checker_which_is_a_loosening():
    assert functions.grant_loosening("risk", CATALOGUE) == ["checker_added"]


def test_giving_audit_is_a_loosening_too():
    assert functions.grant_loosening("audit", CATALOGUE) == ["checker_added"]


def test_giving_a_first_line_function_is_not_a_loosening():
    assert functions.grant_loosening("developer", CATALOGUE) == []


def test_a_members_line_is_the_line_of_what_they_hold():
    assert functions.line_of(["risk", "legal"], CATALOGUE) == 2
    assert functions.line_of([], CATALOGUE) is None


def test_a_new_function_name_is_lower_case_letters_digits_and_underscores():
    assert functions.name_allowed("data_protection") is True
    assert functions.name_allowed("head_of_unit_2") is True
    for bad in ("Data Protection", "2nd_line", "a", "x" * 41, "risk-team", ""):
        assert functions.name_allowed(bad) is False, bad


def test_a_project_can_add_functions_to_the_first_two_lines_only():
    assert functions.line_allowed(1) is True
    assert functions.line_allowed(2) is True
    assert functions.line_allowed(3) is False
