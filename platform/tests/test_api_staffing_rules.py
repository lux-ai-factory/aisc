"""How many people check each kind of task: one number per kind, 0 to 5, changed by owners.

work.staffing_rule keeps one row per change and the latest wins; a kind with no row needs no checker, so a
new project starts as the light preset. Two presets set every kind at once.
"""
from __future__ import annotations

import pytest

from tests.conftest import ALICE, needs_database, project_db

pytestmark = needs_database

BOB = "00000000-0000-0000-0000-0000000000b0"      # editor
VERA = "00000000-0000-0000-0000-0000000000f0"     # viewer


@pytest.fixture
def team(make_project):
    return make_project(owner=ALICE, editors=(BOB,), viewers=(VERA,))


def rules(client, as_user, project, who=ALICE):
    got = client.get(f"/projects/{project['slug']}/work/rules", headers=as_user(who))
    assert got.status_code == 200, got.text
    return {r["kind"]: r["checkers"] for r in got.json()["rules"]}


def put_rule(client, as_user, project, kind, checkers, who=ALICE):
    return client.put(f"/projects/{project['slug']}/work/rules/{kind}", json={"checkers": checkers},
                      headers=as_user(who))


def preset(client, as_user, project, name, who=ALICE):
    return client.post(f"/projects/{project['slug']}/work/preset", json={"preset": name}, headers=as_user(who))


def test_a_new_project_needs_no_checker_for_any_kind(client, as_user, team):
    from platform_service.work.kinds import KINDS

    got = client.get(f"/projects/{team['slug']}/work/rules", headers=as_user(VERA))
    assert got.status_code == 200, got.text
    assert [(r["kind"], r["checkers"]) for r in got.json()["rules"]] == [(kind, 0) for kind in KINDS]


def test_an_owner_sets_the_checkers_of_a_kind(client, as_user, team):
    changed = put_rule(client, as_user, team, "fill_checklist", 2)
    assert changed.status_code == 200, changed.text
    got = rules(client, as_user, team)
    assert got["fill_checklist"] == 2
    assert got["rate_risks"] == 0


def test_each_change_is_a_row_and_the_latest_wins(client, as_user, team, dsn):
    put_rule(client, as_user, team, "fill_checklist", 2)
    put_rule(client, as_user, team, "fill_checklist", 1)
    assert rules(client, as_user, team)["fill_checklist"] == 1
    with project_db(dsn, team) as conn:
        rows = conn.execute("select checkers, set_by_subject from work.staffing_rule where kind = 'fill_checklist'"
                            " order by set_at, id").fetchall()
    assert rows == [(2, ALICE), (1, ALICE)]


def test_an_editor_cannot_change_the_rule(client, as_user, team):
    assert put_rule(client, as_user, team, "fill_checklist", 1, who=BOB).status_code == 403
    assert preset(client, as_user, team, "four_eyes", who=BOB).status_code == 403
    assert rules(client, as_user, team)["fill_checklist"] == 0


@pytest.mark.parametrize("checkers", [-1, 6, "1", 1.5, None])
def test_the_checkers_are_a_whole_number_from_0_to_5(client, as_user, team, checkers):
    assert put_rule(client, as_user, team, "fill_checklist", checkers).status_code == 422
    assert rules(client, as_user, team)["fill_checklist"] == 0


def test_an_unknown_kind_has_no_rule(client, as_user, team):
    assert put_rule(client, as_user, team, "bake_cake", 1).status_code == 404


def test_four_eyes_sets_one_checker_except_for_launching_and_composing(client, as_user, team):
    applied = preset(client, as_user, team, "four_eyes")
    assert applied.status_code == 200, applied.text
    got = rules(client, as_user, team)
    assert got["describe_system"] == 1 and got["fill_checklist"] == 1
    assert got["launch_run"] == 0 and got["compose_report"] == 0


def test_light_sets_every_kind_back_to_no_checker(client, as_user, team):
    put_rule(client, as_user, team, "fill_checklist", 3)
    preset(client, as_user, team, "four_eyes")
    assert preset(client, as_user, team, "light").status_code == 200
    assert set(rules(client, as_user, team).values()) == {0}


def test_an_unknown_preset_is_refused(client, as_user, team):
    assert preset(client, as_user, team, "bank").status_code == 422
    assert set(rules(client, as_user, team).values()) == {0}
