"""One AI system per project, and versions of it that stay as they were.

A project has exactly one AI system: what qualification describes, what the
engine tests, what the dashboard reports on. Its latest version is a draft
until something depends on it (an evaluation runs against it, or its AI card
is submitted); then it is frozen, and the next edit makes the version after
it rather than changing what the evaluation or the card was about.

These are the rules on their own, so they need no database.
"""
import pytest

from platform_service.ai_system import InvalidSystem, plan_edit

DRAFT = {"pid": "v1", "number": 1, "name": "MCAS", "release": "1.0",
         "provider": "LIST", "description": "Scores loans", "frozen_at": None}
FROZEN = {**DRAFT, "frozen_at": "2026-09-23T15:00:00Z"}


def test_a_draft_is_edited_in_place():
    plan = plan_edit(DRAFT, {"description": "Scores microcredit loans"})
    assert plan == {"action": "update", "pid": "v1",
                    "fields": {"description": "Scores microcredit loans"}}


def test_a_frozen_version_is_never_edited_the_edit_makes_the_next_one():
    plan = plan_edit(FROZEN, {"description": "Scores microcredit loans"})
    assert plan == {"action": "fork", "from_pid": "v1", "number": 2,
                    "fields": {"name": "MCAS", "release": "1.0", "provider": "LIST",
                               "description": "Scores microcredit loans"}}


def test_the_next_version_starts_as_a_copy_of_the_frozen_one():
    plan = plan_edit(FROZEN, {"release": "1.1"})
    assert plan["fields"] == {"name": "MCAS", "release": "1.1", "provider": "LIST",
                              "description": "Scores loans"}


def test_writing_what_is_already_there_is_not_an_edit():
    # a form saved without changes must not mint a version nobody asked for
    assert plan_edit(FROZEN, {"name": "MCAS", "release": "1.0"}) == {"action": "none", "pid": "v1"}
    assert plan_edit(DRAFT, {}) == {"action": "none", "pid": "v1"}


def test_surrounding_space_is_not_a_change():
    assert plan_edit(FROZEN, {"name": "  MCAS "}) == {"action": "none", "pid": "v1"}


def test_a_component_change_on_a_frozen_version_needs_a_draft_to_land_in():
    # the engine changes a component: no identity field moves, but a frozen
    # version cannot take the change, so there has to be a version after it
    plan = plan_edit(FROZEN, {}, needs_draft=True)
    assert plan == {"action": "fork", "from_pid": "v1", "number": 2,
                    "fields": {"name": "MCAS", "release": "1.0", "provider": "LIST",
                               "description": "Scores loans"}}


def test_a_draft_already_takes_component_changes():
    assert plan_edit(DRAFT, {}, needs_draft=True) == {"action": "none", "pid": "v1"}


def test_a_system_without_a_name_is_refused():
    with pytest.raises(InvalidSystem):
        plan_edit(DRAFT, {"name": "   "})


def test_an_empty_optional_field_is_stored_as_nothing():
    plan = plan_edit(DRAFT, {"release": "  "})
    assert plan == {"action": "update", "pid": "v1", "fields": {"release": None}}


def test_only_the_identity_fields_are_edited_here():
    with pytest.raises(InvalidSystem):
        plan_edit(DRAFT, {"frozen_at": None})
