"""Which submitted tasks a sampled rule checks.

File review by sampling is worth something only if the person who did the work cannot know, before
handing it in, whether it will be looked at, and cannot get another draw by handing it in again.
"""
from __future__ import annotations

import hashlib
import hmac

from platform_service.work import staffing

KEY = b"a project's ledger key, thirty-two bytes."
OTHER_KEY = b"another project's ledger key, 32 bytes.."


def subjects(n):
    return [f"submission-{i:05d}" for i in range(n)]


def test_the_same_subject_always_gets_the_same_answer():
    first = [staffing.draw_sample(KEY, s, 5) for s in subjects(200)]
    again = [staffing.draw_sample(KEY, s, 5) for s in subjects(200)]
    assert first == again


def test_the_draw_is_the_keyed_hash_of_the_subject_so_an_auditor_can_recompute_it():
    for s in subjects(50):
        digest = hmac.new(KEY, s.encode(), hashlib.sha256).digest()
        assert staffing.draw_sample(KEY, s, 5) is (int.from_bytes(digest, "big") % 5 == 0)


def test_another_projects_key_draws_other_tasks():
    here = [staffing.draw_sample(KEY, s, 5) for s in subjects(200)]
    there = [staffing.draw_sample(OTHER_KEY, s, 5) for s in subjects(200)]
    assert here != there


def test_about_one_task_in_five_is_drawn():
    drawn = sum(staffing.draw_sample(KEY, s, 5) for s in subjects(5000))
    assert 900 <= drawn <= 1100, f"{drawn} of 5000 drawn at one in five"


def test_about_one_task_in_fifty_is_drawn():
    drawn = sum(staffing.draw_sample(KEY, s, 50) for s in subjects(5000))
    assert 60 <= drawn <= 140, f"{drawn} of 5000 drawn at one in fifty"


def test_the_drawn_tasks_do_not_follow_the_order_they_were_made_in():
    picks = [i for i, s in enumerate(subjects(500)) if staffing.draw_sample(KEY, s, 5)]
    gaps = {b - a for a, b in zip(picks, picks[1:])}
    assert len(gaps) > 3, "every fifth task in a row could be counted by the person doing them"


def test_the_answer_is_a_plain_yes_or_no():
    assert staffing.draw_sample(KEY, "submission-1", 5) in (True, False)
