"""Submitting a task for check and signing it off, through the platform's API.

A doer of the current round submits: the parts they hold are released, the content hash and the card state
are stored and checkers_needed is copied from the rule; with 0 checkers the task is done at once. Anyone in
the project who did not work on the round signs: agree, or send back with a reason, on the content the page
showed. Done when the agreeing sign-offs reach checkers_needed; a send back opens the task again, its parts
with their last holders.
"""
from __future__ import annotations

import psycopg
import pytest

from tests import work_content as wc
from tests.conftest import ALICE, needs_database, project_db

pytestmark = needs_database

BOB = "00000000-0000-0000-0000-0000000000b0"      # editor
CAROL = "00000000-0000-0000-0000-0000000000c0"    # editor
DAN = "00000000-0000-0000-0000-0000000000d0"      # editor
VERA = "00000000-0000-0000-0000-0000000000f0"     # viewer
TASK = "/projects/{slug}/work/fill_checklist/s1"


@pytest.fixture
def team(make_project, client, as_user, dsn):
    if not wc.SUPERUSER:
        pytest.skip("PLATFORM_TEST_SUPERUSER_URL is not set")
    project = make_project(owner=ALICE, editors=(BOB, CAROL, DAN), viewers=(VERA,))
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
    return client.post(TASK.format(slug=project["slug"]) + "/submit", headers=as_user(who))


def task(client, as_user, project, who=ALICE):
    got = client.get(TASK.format(slug=project["slug"]), headers=as_user(who))
    assert got.status_code == 200, got.text
    return got.json()


def sign(client, as_user, project, who, answer="agree", reason=None, content_hash=None):
    body = {"answer": answer, "content_hash": content_hash or task(client, as_user, project)["content_hash"]}
    if reason is not None:
        body["reason"] = reason
    return client.post(TASK.format(slug=project["slug"]) + "/sign", json=body, headers=as_user(who))


def holders(dsn, project):
    with project_db(dsn, project) as conn:
        return dict(conn.execute("select part, holder_subject from work.hold").fetchall())


def stored(dsn, project):
    with project_db(dsn, project) as conn:
        return conn.execute("select state, round, checkers_needed, content_hash, card_state from work.task").fetchone()


# submit

def test_a_doer_submits_and_the_task_waits_for_its_checkers(client, as_user, team, dsn):
    checkers(client, as_user, team, 1)
    save(dsn, team, BOB)
    submitted = submit(client, as_user, team, BOB)
    assert submitted.status_code == 200, submitted.text
    state, round_, needed, content_hash, _ = stored(dsn, team)
    assert (state, round_, needed) == ("in_check", 1, 1)
    with project_db(dsn, team) as conn:
        assert content_hash == conn.execute("select work.content_hash('fill_checklist', 's1')").fetchone()[0]


def test_submitting_stores_the_card_state(client, as_user, team, dsn):
    wc.card_version(team, "11111111-1111-1111-1111-111111111111", 1)
    save(dsn, team, BOB)
    assert submit(client, as_user, team, BOB).status_code == 200
    assert stored(dsn, team)[4] == {"version": "11111111-1111-1111-1111-111111111111", "number": 1, "revision": 1}


def test_submitting_releases_the_submitters_parts(client, as_user, team, dsn):
    checkers(client, as_user, team, 1)
    save(dsn, team, BOB)
    save(dsn, team, BOB, "data", "Data")
    assert holders(dsn, team) == {"governance": BOB, "data": BOB}
    assert submit(client, as_user, team, BOB).status_code == 200
    assert holders(dsn, team) == {}


def test_with_no_checker_a_submitted_task_is_done_at_once(client, as_user, team, dsn):
    save(dsn, team, BOB)
    submitted = submit(client, as_user, team, BOB)
    assert submitted.status_code == 200, submitted.text
    assert stored(dsn, team)[:3] == ("done", 1, 0)


def test_the_checkers_needed_are_copied_when_the_task_is_submitted(client, as_user, team, dsn):
    checkers(client, as_user, team, 2)
    save(dsn, team, BOB)
    submit(client, as_user, team, BOB)
    checkers(client, as_user, team, 0)
    assert stored(dsn, team)[:3] == ("in_check", 1, 2)


def test_submitting_is_refused_while_someone_else_holds_a_part_and_says_who_holds_what(client, as_user, team, dsn):
    save(dsn, team, BOB)
    save(dsn, team, CAROL, "data", "Data")
    refused = submit(client, as_user, team, BOB)
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "not_holder"
    assert CAROL in detail["message"] and "Data" in detail["message"], detail["message"]
    assert [(h["label"], h["holder"]) for h in detail["held"]] == [("Data", CAROL)]
    assert stored(dsn, team)[0] == "open"
    assert holders(dsn, team) == {"governance": BOB, "data": CAROL}


def test_someone_who_did_not_work_on_the_round_cannot_submit(client, as_user, team, dsn):
    save(dsn, team, BOB)
    assert submit(client, as_user, team, CAROL).status_code == 403
    assert submit(client, as_user, team, VERA).status_code == 403
    assert stored(dsn, team)[0] == "open"


def test_a_task_in_check_cannot_be_submitted_again(client, as_user, team, dsn):
    checkers(client, as_user, team, 1)
    save(dsn, team, BOB)
    submit(client, as_user, team, BOB)
    again = submit(client, as_user, team, BOB)
    assert again.status_code == 409, again.text
    assert again.json()["detail"]["code"] == "not_final"


def test_a_task_that_does_not_exist_cannot_be_submitted(client, as_user, team):
    assert submit(client, as_user, team, BOB).status_code == 404


@pytest.mark.parametrize("kind,subject,part", [("describe_system", "card", "purpose"),
                                               ("rate_risks", "11111111-1111-1111-1111-111111111111", "register")])
def test_every_held_kind_is_submitted_with_its_content_hash(client, as_user, team, dsn, kind, subject, part):
    wc.card_version(team, "11111111-1111-1111-1111-111111111111", 1)
    wc.card(team, "c1", "11111111-1111-1111-1111-111111111111")
    save(dsn, team, BOB, part, part.title(), subject=subject, kind=kind)
    submitted = client.post(f"/projects/{team['slug']}/work/{kind}/{subject}/submit", headers=as_user(BOB))
    assert submitted.status_code == 200, submitted.text
    with project_db(dsn, team) as conn:
        got = conn.execute("select content_hash, work.content_hash(kind, subject) from work.task").fetchone()
    assert got[0] is not None and got[0] == got[1]


# sign

def test_one_checker_agreeing_makes_the_task_done(client, as_user, team, dsn):
    checkers(client, as_user, team, 1)
    save(dsn, team, BOB)
    submit(client, as_user, team, BOB)
    signed = sign(client, as_user, team, CAROL)
    assert signed.status_code == 200, signed.text
    assert stored(dsn, team)[0] == "done"


def test_with_two_checkers_the_task_is_done_at_the_second_agreement(client, as_user, team, dsn):
    checkers(client, as_user, team, 2)
    save(dsn, team, BOB)
    submit(client, as_user, team, BOB)
    assert sign(client, as_user, team, CAROL).status_code == 200
    assert stored(dsn, team)[0] == "in_check"
    assert sign(client, as_user, team, VERA).status_code == 200
    assert stored(dsn, team)[0] == "done"


def test_one_person_signs_a_round_once(client, as_user, team, dsn):
    checkers(client, as_user, team, 2)
    save(dsn, team, BOB)
    submit(client, as_user, team, BOB)
    sign(client, as_user, team, CAROL)
    assert sign(client, as_user, team, CAROL).status_code == 409
    assert stored(dsn, team)[0] == "in_check"


def test_a_doer_cannot_sign(client, as_user, team, dsn):
    checkers(client, as_user, team, 1)
    save(dsn, team, BOB)
    save(dsn, team, CAROL, "data", "Data")
    with project_db(dsn, team) as conn:
        conn.execute("delete from work.hold where holder_subject = %s", (CAROL,))
    submit(client, as_user, team, BOB)
    assert sign(client, as_user, team, BOB).status_code == 403
    assert sign(client, as_user, team, CAROL).status_code == 403
    assert stored(dsn, team)[0] == "in_check"


def test_a_sign_off_on_content_other_than_the_page_showed_is_refused(client, as_user, team, dsn):
    checkers(client, as_user, team, 1)
    save(dsn, team, BOB)
    submit(client, as_user, team, BOB)
    refused = sign(client, as_user, team, CAROL, content_hash="0" * 64)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "upstream_moved"
    assert "changed" in refused.json()["detail"]["message"]
    assert stored(dsn, team)[0] == "in_check"


def test_a_sign_off_after_the_content_changed_is_refused(client, as_user, team, dsn):
    checkers(client, as_user, team, 1)
    save(dsn, team, BOB)
    submit(client, as_user, team, BOB)
    shown = task(client, as_user, team)["content_hash"]
    wc.sql(team, "UPDATE controls.submission_answer SET answer = 'no'")
    refused = sign(client, as_user, team, CAROL, content_hash=shown)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "upstream_moved"
    assert stored(dsn, team)[0] == "in_check"


def test_sending_back_needs_a_reason(client, as_user, team, dsn):
    checkers(client, as_user, team, 1)
    save(dsn, team, BOB)
    submit(client, as_user, team, BOB)
    assert sign(client, as_user, team, CAROL, answer="send_back").status_code == 422
    assert sign(client, as_user, team, CAROL, answer="send_back", reason="  ").status_code == 422
    assert stored(dsn, team)[0] == "in_check"


def test_a_send_back_opens_the_task_in_the_same_round_with_each_part_back_to_its_last_holder(client, as_user,
                                                                                             team, dsn):
    checkers(client, as_user, team, 1)
    save(dsn, team, BOB)
    save(dsn, team, CAROL, "data", "Data")
    with project_db(dsn, team) as conn:
        conn.execute("delete from work.hold where holder_subject = %s", (CAROL,))   # Carol released Data
    submit(client, as_user, team, BOB)
    sent = sign(client, as_user, team, DAN, answer="send_back", reason="Question 1 needs evidence")
    assert sent.status_code == 200, sent.text
    assert stored(dsn, team)[:2] == ("open", 1)
    assert holders(dsn, team) == {"governance": BOB, "data": CAROL}


def test_an_agreement_given_before_a_send_back_counts_only_on_the_same_content(client, as_user, team, dsn):
    checkers(client, as_user, team, 2)
    save(dsn, team, BOB)
    submit(client, as_user, team, BOB)
    sign(client, as_user, team, CAROL)
    sign(client, as_user, team, DAN, answer="send_back", reason="Question 1 needs evidence")
    wc.sql(team, "UPDATE controls.submission_answer SET answer = 'yes, see the policy'")
    save(dsn, team, BOB)
    submit(client, as_user, team, BOB)
    assert sign(client, as_user, team, VERA).status_code == 200
    assert stored(dsn, team)[0] == "in_check"          # Carol agreed to the earlier content


def test_a_task_not_in_check_cannot_be_signed(client, as_user, team, dsn):
    save(dsn, team, BOB)
    with project_db(dsn, team) as conn:
        current = conn.execute("select work.content_hash('fill_checklist', 's1')").fetchone()[0]
    refused = sign(client, as_user, team, CAROL, content_hash=current)
    assert refused.status_code == 409, refused.text
    assert stored(dsn, team)[0] == "open"


def test_a_stranger_cannot_sign(client, as_user, team, dsn):
    checkers(client, as_user, team, 1)
    save(dsn, team, BOB)
    submit(client, as_user, team, BOB)
    assert sign(client, as_user, team, "00000000-0000-0000-0000-000000000999",
                content_hash="0" * 64).status_code == 404


def test_a_save_on_a_done_task_starts_a_round_whose_check_starts_again(client, as_user, team, dsn):
    checkers(client, as_user, team, 1)
    save(dsn, team, BOB)
    submit(client, as_user, team, BOB)
    sign(client, as_user, team, CAROL)
    wc.sql(team, "UPDATE controls.submission_answer SET answer = 'no'")
    save(dsn, team, DAN)
    assert stored(dsn, team)[:2] == ("open", 2)
    assert submit(client, as_user, team, DAN).status_code == 200
    assert stored(dsn, team)[0] == "in_check"            # Carol's agreement was in round 1
    assert task(client, as_user, team)["sign_offs"] == []
    assert sign(client, as_user, team, BOB).status_code == 200   # Bob did not work on round 2
    assert stored(dsn, team)[0] == "done"


def test_the_sign_offs_are_never_changed_or_removed(client, as_user, team, dsn):
    checkers(client, as_user, team, 1)
    save(dsn, team, BOB)
    submit(client, as_user, team, BOB)
    sign(client, as_user, team, CAROL)
    for statement in ("UPDATE work.sign_off SET signer_name = 'Someone else'", "DELETE FROM work.sign_off",
                      "TRUNCATE work.sign_off"):
        with pytest.raises(psycopg.Error):
            wc.sql(team, statement)
    assert wc.sql(team, "SELECT count(*) FROM work.sign_off") == [(1,)]


# the task as a page reads it

def test_a_task_says_its_round_state_checkers_doers_and_sign_offs(client, as_user, team, dsn):
    checkers(client, as_user, team, 2)
    save(dsn, team, BOB)
    save(dsn, team, BOB, "data", "Data")
    submit(client, as_user, team, BOB)
    sign(client, as_user, team, CAROL)
    got = task(client, as_user, team, who=VERA)
    assert (got["round"], got["state"], got["checkers_needed"]) == (1, "in_check", 2)
    assert sorted((d["part"], d["person_subject"]) for d in got["doers"]) == [("data", BOB), ("governance", BOB)]
    assert [(s["signer_subject"], s["answer"]) for s in got["sign_offs"]] == [(CAROL, "agree")]
    assert got["submitted_by"] == BOB and got["submitted_at"]


def test_a_save_on_a_submitted_task_is_refused_with_who_submitted_it_and_when(client, as_user, team, dsn):
    from aisc_identity import holds

    checkers(client, as_user, team, 1)
    save(dsn, team, BOB)
    submit(client, as_user, team, BOB)
    with project_db(dsn, team, role="controls_rw") as conn:
        with pytest.raises(holds.HoldRefused) as refused:
            with conn.transaction():
                holds.claim_for_save(conn, "fill_checklist", "s1", "governance", "Governance", CAROL, "Carol")
    refusal = refused.value.refusal
    assert (refusal.code, refusal.current.changed_by) == ("not_final", BOB)
    assert refusal.current.changed_at[:10] == task(client, as_user, team)["submitted_at"][:10]
    assert refusal.message.startswith(f"{BOB} submitted Governance for check at "), refusal.message


def test_submitting_the_card_waits_for_a_correction_in_progress_and_neither_deadlocks(team, dsn):
    """A correction claims the card's sections, then takes the card lock once the platform counted its revision
    (spec, section 3). A submit of the card that held the card lock while waiting for the correction's claim
    would wait on it while it waits for the lock."""
    import threading
    import time

    from platform_service.work import checks

    save(dsn, team, BOB, "purpose", "Intended purpose", subject="card", kind="describe_system")
    correction = project_db(dsn, team, role="qualification_rw")
    correction.autocommit = False
    outcome = {}

    def submitting():
        try:
            with project_db(dsn, team) as conn, conn.transaction():
                outcome["submit"] = checks.submit(conn, kind="describe_system", subject="card",
                                                  person_subject=BOB, person_name=BOB).state
        except psycopg.Error as error:
            outcome["submit"] = error.sqlstate

    try:
        correction.execute("select work.claim_for_save('describe_system', 'card', 'purpose', 'Intended purpose',"
                           " %s, %s)", (BOB, BOB))
        other = threading.Thread(target=submitting)
        other.start()
        time.sleep(0.5)
        assert other.is_alive(), f"the submit did not wait for the correction: {outcome}"
        correction.execute("select pg_advisory_xact_lock(hashtext('project.system'))")
        correction.commit()
        other.join(timeout=10)
    except psycopg.Error as error:
        outcome["correction"] = error.sqlstate
    finally:
        correction.rollback()
        correction.close()
    assert outcome == {"submit": "done"}
