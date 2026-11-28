"""What the work pages read from the platform: My tasks (across the caller's projects), a project's work board,
who checks each kind, and a task as the sign-off page and the held pages see it.

The pages decide nothing: what a person may do on each row (take, release, take over, sign, change the rule)
is said by the platform, from the same rules its write routes enforce.
"""
from __future__ import annotations

import uuid

import pytest

from tests import work_content as wc
from tests.conftest import ALICE, needs_database, project_db

pytestmark = needs_database

BOB = "00000000-0000-0000-0000-0000000000b0"      # editor
CAROL = "00000000-0000-0000-0000-0000000000c0"    # editor
VERA = "00000000-0000-0000-0000-0000000000f0"     # viewer
TASK = "/projects/{slug}/work/fill_checklist/s1"


@pytest.fixture
def team(make_project, client, as_user):
    if not wc.SUPERUSER:
        pytest.skip("PLATFORM_TEST_SUPERUSER_URL is not set")
    project = make_project(owner=ALICE, editors=(BOB, CAROL), viewers=(VERA,))
    wc.make_tables(project)
    wc.sql(project, 'INSERT INTO controls.submission_answer ("submissionId", "questionId", answer, score)'
                    " VALUES ('s1', 'q1', 'yes', 4)")
    assert client.put(f"/projects/{project['slug']}/work/holds", json={"on": True},
                      headers=as_user(ALICE)).status_code == 200
    return project


def save(dsn, project, who, part="governance", label="Governance", subject="s1", kind="fill_checklist"):
    with project_db(dsn, project, role="controls_rw") as conn:
        conn.execute("select work.claim_for_save(%s, %s, %s, %s, %s, %s)", (kind, subject, part, label, who, who))


def checkers(client, as_user, project, n, kind="fill_checklist"):
    assert client.put(f"/projects/{project['slug']}/work/rules/{kind}", json={"checkers": n},
                      headers=as_user(ALICE)).status_code == 200


def submit(client, as_user, project, who):
    answer = client.post(TASK.format(slug=project["slug"]) + "/submit", headers=as_user(who))
    assert answer.status_code == 200, answer.text
    return answer.json()


def mine(client, as_user, who, project=None):
    """My tasks of `who`, kept to `project` when given: the suite's people are members of other tests' projects."""
    got = client.get("/work/mine", headers=as_user(who))
    assert got.status_code == 200, got.text
    if project is None:
        return got.json()
    return {name: [row for row in rows if row["project"] == project["slug"]] for name, rows in got.json().items()}


def board(client, as_user, project, who):
    got = client.get(f"/projects/{project['slug']}/work", headers=as_user(who))
    assert got.status_code == 200, got.text
    return got.json()


def task(client, as_user, project, who):
    got = client.get(TASK.format(slug=project["slug"]), headers=as_user(who))
    assert got.status_code == 200, got.text
    return got.json()


# My tasks

def test_my_tasks_lists_the_parts_i_hold_with_their_project_and_since_when(client, as_user, team, dsn):
    save(dsn, team, BOB)
    held = mine(client, as_user, BOB, team)["held"]
    assert [(h["project"], h["kind"], h["subject"], h["part"], h["label"]) for h in held] == [
        (team["slug"], "fill_checklist", "s1", "governance", "Governance")]
    assert held[0]["project_name"] == team["name"] and held[0]["kind_label"] == "Fill a checklist"
    assert held[0]["since"]
    assert mine(client, as_user, CAROL, team)["held"] == []


def test_my_tasks_lists_what_waits_for_my_sign_off_until_i_agree(client, as_user, team, dsn):
    checkers(client, as_user, team, 2)
    save(dsn, team, BOB)
    submit(client, as_user, team, BOB)
    waiting = mine(client, as_user, CAROL, team)["to_sign"]
    assert [(t["project"], t["kind"], t["subject"], t["submitted_by_name"]) for t in waiting] == [
        (team["slug"], "fill_checklist", "s1", BOB)]
    assert mine(client, as_user, BOB, team)["to_sign"] == [], "a doer of the round does not check it"
    agreed = client.post(TASK.format(slug=team["slug"]) + "/sign", headers=as_user(CAROL),
                         json={"answer": "agree", "content_hash": waiting[0]["content_hash"]})
    assert agreed.status_code == 200, agreed.text
    assert mine(client, as_user, CAROL, team)["to_sign"] == []
    assert len(mine(client, as_user, VERA, team)["to_sign"]) == 1, "a viewer may sign, and still has to"


def test_my_tasks_lists_what_was_sent_back_to_me_with_the_reason(client, as_user, team, dsn):
    checkers(client, as_user, team, 1)
    save(dsn, team, BOB)
    done = submit(client, as_user, team, BOB)
    sent = client.post(TASK.format(slug=team["slug"]) + "/sign", headers=as_user(CAROL),
                       json={"answer": "send_back", "reason": "Governance needs the board's minutes",
                             "content_hash": done["content_hash"]})
    assert sent.status_code == 200, sent.text
    back = mine(client, as_user, BOB, team)["sent_back"]
    assert [(t["kind"], t["subject"], t["by"], t["reason"]) for t in back] == [
        ("fill_checklist", "s1", CAROL, "Governance needs the board's minutes")]
    assert mine(client, as_user, CAROL, team)["sent_back"] == []


def test_my_tasks_lists_the_parts_nobody_holds_that_i_could_take(client, as_user, team, dsn):
    save(dsn, team, BOB)
    save(dsn, team, BOB, "data", "Data")
    assert client.post(TASK.format(slug=team["slug"]) + "/parts/data/release",
                       headers=as_user(BOB)).status_code == 200
    free = mine(client, as_user, CAROL, team)["takeable"]
    assert [(f["project"], f["kind"], f["part"], f["label"]) for f in free] == [
        (team["slug"], "fill_checklist", "data", "Data")]
    assert mine(client, as_user, VERA, team)["takeable"] == [], "a viewer takes nothing"


def test_my_tasks_leaves_out_projects_i_am_not_in(client, as_user, team, dsn, make_project):
    save(dsn, team, BOB)
    outsider = str(uuid.uuid4())
    assert mine(client, as_user, outsider) == {"held": [], "offered": [], "to_sign": [], "sent_back": [],
                                               "takeable": []}


# the work board

def test_the_board_lists_each_task_and_part_with_its_holder_since_when_and_state(client, as_user, team, dsn):
    save(dsn, team, BOB)
    save(dsn, team, CAROL, "data", "Data")
    seen = board(client, as_user, team, VERA)
    assert [(t["kind"], t["subject"], t["state"], t["round"]) for t in seen["tasks"]] == [
        ("fill_checklist", "s1", "open", 1)]
    parts = {p["key"]: p for p in seen["tasks"][0]["parts"]}
    assert (parts["governance"]["label"], parts["governance"]["holder_subject"]) == ("Governance", BOB)
    assert parts["data"]["holder_subject"] == CAROL and parts["data"]["since"]
    assert seen["holding"] is True


def test_the_board_says_what_the_caller_may_do(client, as_user, team, dsn):
    save(dsn, team, BOB)
    assert board(client, as_user, team, VERA)["may"] == {"take": False, "take_over": False}
    assert board(client, as_user, team, CAROL)["may"] == {"take": True, "take_over": False}
    assert board(client, as_user, team, CAROL)["you"] == CAROL, "so the page knows which parts are the caller's"
    assert board(client, as_user, team, ALICE)["may"] == {"take": True, "take_over": True}


def test_the_board_names_who_an_owner_may_give_a_part_to(client, as_user, team, dsn):
    save(dsn, team, BOB)
    to = board(client, as_user, team, ALICE)["give_to"]
    assert sorted(m["subject"] for m in to) == sorted([ALICE, BOB, CAROL]), "editors and owners, not viewers"
    assert board(client, as_user, team, CAROL)["give_to"] == []


def test_the_board_is_refused_to_a_stranger(client, as_user, team):
    assert client.get(f"/projects/{team['slug']}/work",
                      headers=as_user("00000000-0000-0000-0000-0000000000e0")).status_code == 404


def test_giving_a_part_to_someone_needs_a_reason_and_an_owner(client, as_user, team, dsn):
    save(dsn, team, BOB)
    url = TASK.format(slug=team["slug"]) + "/parts/governance/take-over"
    no_reason = client.post(url, json={"to": CAROL, "reason": "  "}, headers=as_user(ALICE))
    assert no_reason.status_code == 422
    assert client.post(url, json={"to": CAROL, "reason": "Bob is away"}, headers=as_user(CAROL)).status_code == 403
    given = client.post(url, json={"to": CAROL, "reason": "Bob is away"}, headers=as_user(ALICE))
    assert given.status_code == 200, given.text
    parts = board(client, as_user, team, ALICE)["tasks"][0]["parts"]
    assert parts[0]["holder_subject"] == CAROL


# who checks each kind

def test_the_rules_say_whether_the_caller_may_change_them(client, as_user, team):
    rules = lambda who: client.get(f"/projects/{team['slug']}/work/rules", headers=as_user(who)).json()
    assert rules(ALICE)["may_change"] is True
    assert rules(CAROL)["may_change"] is False
    assert rules(VERA)["may_change"] is False
    assert [p["name"] for p in rules(VERA)["presets"]] == ["light", "four_eyes"]


# a task, as the sign-off page and a held page see it

def test_a_task_says_which_parts_are_the_callers_and_whether_they_may_take(client, as_user, team, dsn):
    save(dsn, team, BOB)
    save(dsn, team, BOB, "data", "Data")
    client.post(TASK.format(slug=team["slug"]) + "/parts/data/release", headers=as_user(BOB))
    seen = task(client, as_user, team, BOB)
    assert {p["key"]: p["yours"] for p in seen["parts"]} == {"governance": True, "data": False}
    assert seen["may"]["take"] is True
    assert task(client, as_user, team, VERA)["may"]["take"] is False


def test_each_part_says_what_the_caller_may_do_on_it(client, as_user, team, dsn):
    """Take a part nobody holds (an editor or owner), release your own, take over someone else's (an owner),
    while the task is open; nothing while it is in check."""
    save(dsn, team, BOB)
    save(dsn, team, BOB, "data", "Data")
    client.post(TASK.format(slug=team["slug"]) + "/parts/data/release", headers=as_user(BOB))
    acts = lambda who: {p["key"]: (p["can_take"], p["can_release"], p["can_take_over"])
                        for p in task(client, as_user, team, who)["parts"]}
    assert acts(BOB) == {"governance": (False, True, False), "data": (True, False, False)}
    assert acts(CAROL) == {"governance": (False, False, False), "data": (True, False, False)}
    assert acts(ALICE) == {"governance": (False, False, True), "data": (True, False, True)}
    assert acts(VERA) == {"governance": (False, False, False), "data": (False, False, False)}
    board_parts = {p["key"]: (p["can_take"], p["can_release"], p["can_take_over"])
                   for p in board(client, as_user, team, ALICE)["tasks"][0]["parts"]}
    assert board_parts == acts(ALICE)
    client.post(TASK.format(slug=team["slug"]) + "/parts/governance/release", headers=as_user(BOB))
    submit(client, as_user, team, BOB)
    assert set(acts(ALICE).values()) == {(False, False, False)}, "a task that is not open changes no hands"


def test_a_task_says_whether_the_caller_may_sign_it(client, as_user, team, dsn):
    checkers(client, as_user, team, 1)
    save(dsn, team, BOB)
    assert task(client, as_user, team, CAROL)["may"]["sign"] is False, "not in check yet"
    submit(client, as_user, team, BOB)
    assert task(client, as_user, team, CAROL)["may"]["sign"] is True
    assert task(client, as_user, team, BOB)["may"]["sign"] is False, "a doer of the round"


def test_a_task_says_why_the_caller_may_not_sign_it(client, as_user, team, dsn):
    # without a reason the sign-off page shows a task in check and no buttons, and the person cannot tell why
    checkers(client, as_user, team, 1)
    save(dsn, team, BOB)
    submit(client, as_user, team, BOB)
    assert "worked on this task in this round" in task(client, as_user, team, BOB)["may"]["sign_why_not"]
    assert task(client, as_user, team, CAROL)["may"]["sign_why_not"] is None


def test_a_task_names_each_doers_part_as_its_page_labels_it(client, as_user, team, dsn):
    save(dsn, team, BOB)
    assert [(d["part"], d["label"]) for d in task(client, as_user, team, VERA)["doers"]] == [
        ("governance", "Governance")]


def test_a_task_names_the_page_that_shows_its_content(client, as_user, team, dsn):
    save(dsn, team, BOB)
    assert task(client, as_user, team, VERA)["page"] == f"/controls/p/{team['slug']}/submissions/s1"


def test_a_task_lists_every_sign_off_and_send_back_of_its_round(client, as_user, team, dsn):
    checkers(client, as_user, team, 1)
    save(dsn, team, BOB)
    done = submit(client, as_user, team, BOB)
    client.post(TASK.format(slug=team["slug"]) + "/sign", headers=as_user(CAROL),
                json={"answer": "send_back", "reason": "Say who decides", "content_hash": done["content_hash"]})
    save(dsn, team, BOB)
    again = submit(client, as_user, team, BOB)
    seen = task(client, as_user, team, VERA)
    assert [(s["signer_name"], s["answer"], s["reason"]) for s in seen["sign_offs"]] == [
        (CAROL, "send_back", "Say who decides")]
    assert seen["state"] == "in_check" and seen["content_hash"] == again["content_hash"]
