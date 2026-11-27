"""The launcher's work pages (docs/specs/who-does-what.md, section 7): My tasks on the launcher, a project's work
board, who checks each kind, and the sign-off page.

The pages decide nothing: they show what the platform answers (tests/test_api_work_pages.py holds the platform to
the same shapes, on a real database) and offer only what it says the person may do. A refusal is said in the
platform's own words. Each page runs under node (launcher_page_bed.py) against answers given here.
"""
from __future__ import annotations

from launcher_page_bed import run_page

ANNA, BOB = "anna-subject", "bob-subject"
TASK = "/api/projects/demo/work/fill_checklist/s1"
PART = TASK + "/parts/governance"
NOT_HOLDER = {"code": "not_holder", "message": "Bob Rossi holds this part since 27 Nov 10:40 UTC.", "current": {}}


def text(out):
    return " | ".join(out["shown"])


def calls(out, method):
    return [(c["path"], c["body"]) for c in out["sent"] if c["method"] == method]


# My tasks, on the launcher

MINE = {
    "held": [{"project": "demo", "project_name": "Demo", "kind": "fill_checklist", "kind_label": "Fill a checklist",
              "subject": "s1", "part": "governance", "label": "Governance", "since": "2026-11-27T10:40:00+00:00"}],
    "offered": [],
    "to_sign": [{"project": "demo", "project_name": "Demo", "kind": "describe_system",
                 "kind_label": "Describe the system", "subject": "card", "round": 1, "content_hash": "abc",
                 "submitted_by_name": "Bob Rossi", "submitted_at": "2026-11-27T11:00:00+00:00",
                 "checkers_needed": 1}],
    "sent_back": [{"project": "demo", "project_name": "Demo", "kind": "rate_risks",
                   "kind_label": "Rate and map the risks", "subject": "v1", "round": 1, "by": "Carla Bianchi",
                   "reason": "Rate the data risk", "at": "2026-11-27T12:00:00+00:00"}],
    "takeable": [{"project": "demo", "project_name": "Demo", "kind": "fill_checklist",
                  "kind_label": "Fill a checklist", "subject": "s1", "part": "data", "label": "Data"}],
}


def launcher(tmp_path, mine=None, **answers):
    return run_page(tmp_path, "index.html", answers={
        "/api/projects": {"status": 200, "body": []},
        "/api/work/mine": mine or {"status": 200, "body": MINE}, **answers})


def test_my_tasks_shows_what_i_hold_what_waits_for_my_sign_off_what_came_back_and_what_i_could_take(tmp_path):
    out = launcher(tmp_path)
    shown = text(out)
    for said in ("Parts I hold", "Governance", "Waiting for my sign-off", "Describe the system", "Bob Rossi",
                 "Sent back to me", "Rate the data risk", "Carla Bianchi", "Parts nobody holds", "Data"):
        assert said in shown, f"{said!r} not on the launcher: {shown}"
    assert ["Sign off", "/sign.html?project=demo&kind=describe_system&subject=card"] in out["links"]
    assert ["Work board", "/work.html?project=demo"] in out["links"]


def test_a_part_nobody_holds_is_taken_from_my_tasks(tmp_path):
    out = run_page(tmp_path, "index.html", answers={
        "/api/projects": {"status": 200, "body": []}, "/api/work/mine": {"status": 200, "body": MINE},
        "/api/projects/demo/work/fill_checklist/s1/parts/data/take": {"status": 200, "body": {}}},
        steps=[{"click": "Take"}])
    assert calls(out, "POST") == [("/api/projects/demo/work/fill_checklist/s1/parts/data/take", None)]


def test_a_refused_take_on_my_tasks_says_the_platforms_words(tmp_path):
    out = run_page(tmp_path, "index.html", answers={
        "/api/projects": {"status": 200, "body": []}, "/api/work/mine": {"status": 200, "body": MINE},
        "/api/projects/demo/work/fill_checklist/s1/parts/data/take": {"status": 409, "body": {"detail": NOT_HOLDER}}},
        steps=[{"click": "Take"}])
    assert NOT_HOLDER["message"] in text(out)


def test_my_tasks_that_cannot_be_read_say_why_and_not_that_there_is_nothing(tmp_path):
    out = launcher(tmp_path, mine={"status": 503, "body": {"detail": "The platform could not reach its database"}})
    assert "could not reach its database" in text(out)
    assert "Nothing" not in text(out)


# the work board

def board_answer(may, you=ANNA, give_to=()):
    """A board with three parts: Bob holds Governance, nobody holds Data, Anna holds Scope; what the caller may do
    on each is said as the platform says it (platform_service/work/board.py, part_actions)."""
    def part(key, label, holder, name, since):
        return {"key": key, "label": label, "holder_subject": holder, "holder_name": name, "since": since,
                "offered_to_subject": None, "offered_to_name": None,
                "can_take": holder is None and may["take"], "can_release": holder == you,
                "can_take_over": may["take_over"] and holder != you}
    return {"project": "demo", "you": you, "role": "x", "holding": True, "may": may, "give_to": list(give_to),
            "tasks": [{"kind": "fill_checklist", "kind_label": "Fill a checklist", "subject": "s1", "state": "open",
                       "round": 1, "checkers_needed": None, "submitted_by_name": None, "submitted_at": None,
                       "parts": [part("governance", "Governance", BOB, "Bob Rossi", "2026-11-27T10:40:00+00:00"),
                                 part("data", "Data", None, None, None),
                                 part("scope", "Scope", ANNA, "Anna", "2026-11-27T09:00:00+00:00")]}]}


def on_board(tmp_path, body, steps=(), **answers):
    return run_page(tmp_path, "work.html", search="?project=demo", steps=list(steps), answers={
        "/api/projects/demo": {"status": 200, "body": {"name": "Demo", "slug": "demo"}},
        "/api/projects/demo/work": {"status": 200, "body": body}, **answers})


def test_the_board_shows_each_task_and_part_with_its_holder_since_when_and_state(tmp_path):
    shown = text(on_board(tmp_path, board_answer({"take": False, "take_over": False})))
    for said in ("Fill a checklist", "Governance", "Bob Rossi", "10:40", "Data", "nobody", "open"):
        assert said in shown, f"{said!r} not on the board: {shown}"


def test_a_viewer_sees_the_board_and_is_offered_nothing(tmp_path):
    out = on_board(tmp_path, board_answer({"take": False, "take_over": False}, you="vera-subject"))
    assert out["buttons"] == []


def test_an_editor_takes_a_free_part_and_releases_their_own(tmp_path):
    out = on_board(tmp_path, board_answer({"take": True, "take_over": False}),
                   steps=[{"click": "Take"}, {"click": "Release"}],
                   **{TASK + "/parts/data/take": {"status": 200, "body": {}},
                      TASK + "/parts/scope/release": {"status": 200, "body": {}}})
    assert sorted(out["buttons"]) == ["Release", "Take"]
    assert calls(out, "POST") == [(TASK + "/parts/data/take", None), (TASK + "/parts/scope/release", None)]


def test_an_owner_gives_a_part_to_someone_with_a_reason(tmp_path):
    out = on_board(tmp_path, board_answer({"take": True, "take_over": True},
                                          give_to=[{"subject": "carla-subject", "name": "Carla", "role": "editor"}]),
                   steps=[{"type": "Give Governance to", "value": "carla-subject"},
                          {"type": "Reason for Governance", "value": "Bob is away this week"},
                          {"click": "Give to"}],
                   **{PART + "/take-over": {"status": 200, "body": {}}})
    assert (PART + "/take-over", {"to": "carla-subject", "reason": "Bob is away this week"}) in calls(out, "POST")


def test_an_owner_takes_a_part_over_and_the_refusal_is_in_the_platforms_words(tmp_path):
    refusal = {"detail": [{"msg": "Value error, say why the part changes hands"}]}
    out = on_board(tmp_path, board_answer({"take": True, "take_over": True}),
                   steps=[{"type": "Reason for Governance", "value": ""}, {"click": "Take over"}],
                   **{PART + "/take-over": {"status": 422, "body": refusal}})
    assert (PART + "/take-over", {"reason": ""}) in calls(out, "POST")
    assert "say why the part changes hands" in text(out)


def test_a_task_in_check_links_to_its_sign_off_page(tmp_path):
    body = board_answer({"take": False, "take_over": False})
    body["tasks"][0]["state"] = "in_check"
    out = on_board(tmp_path, body)
    assert ["Sign-off page", "/sign.html?project=demo&kind=fill_checklist&subject=s1"] in out["links"]


# who does what

RULES = {"may_change": True,
         "presets": [{"name": "light", "checkers": {}}, {"name": "four_eyes", "checkers": {}}],
         "rules": [{"kind": "describe_system", "label": "Describe the system", "checkers": 0, "set_by": None,
                    "set_at": None},
                   {"kind": "fill_checklist", "label": "Fill a checklist", "checkers": 2, "set_by": "Anna",
                    "set_at": "2026-11-27T09:00:00+00:00"}]}


def on_rules(tmp_path, body, steps=(), **answers):
    return run_page(tmp_path, "rules.html", search="?project=demo", steps=list(steps), answers={
        "/api/projects/demo": {"status": 200, "body": {"name": "Demo", "slug": "demo"}},
        "/api/projects/demo/work/rules": {"status": 200, "body": body}, **answers})


def test_who_does_what_lists_the_checkers_of_each_kind(tmp_path):
    shown = text(on_rules(tmp_path, {**RULES, "may_change": False}))
    for said in ("Describe the system", "Fill a checklist", "2", "Anna"):
        assert said in shown, f"{said!r} not on the page: {shown}"


def test_only_an_owner_is_offered_to_change_the_checkers(tmp_path):
    assert on_rules(tmp_path, {**RULES, "may_change": False})["buttons"] == []
    assert "Save" in on_rules(tmp_path, RULES)["buttons"]


def test_an_owner_changes_the_checkers_of_a_kind(tmp_path):
    out = on_rules(tmp_path, RULES, steps=[{"type": "Checkers for Fill a checklist", "value": "1"},
                                           {"click": "Save"}],
                   **{"/api/projects/demo/work/rules/fill_checklist": {"status": 200, "body": {}}})
    assert calls(out, "PUT") == [("/api/projects/demo/work/rules/fill_checklist", {"checkers": 1})]


def test_an_owner_applies_a_preset(tmp_path):
    out = on_rules(tmp_path, RULES, steps=[{"click": "Apply four eyes"}],
                   **{"/api/projects/demo/work/preset": {"status": 200, "body": {}}})
    assert calls(out, "POST") == [("/api/projects/demo/work/preset", {"preset": "four_eyes"})]


def test_a_refused_change_says_the_platforms_words(tmp_path):
    out = on_rules(tmp_path, RULES, steps=[{"type": "Checkers for Fill a checklist", "value": "1"},
                                           {"click": "Save"}],
                   **{"/api/projects/demo/work/rules/fill_checklist": {"status": 403,
                                                                       "body": {"detail": "Only an owner may."}}})
    assert "Only an owner may." in text(out)


# the sign-off page

def task_answer(sign=True):
    return {"kind": "fill_checklist", "kind_label": "Fill a checklist", "subject": "s1", "round": 2,
            "state": "in_check", "checkers_needed": 1, "content_hash": "c0ffee", "card_state": None,
            "submitted_by": BOB, "submitted_by_name": "Bob Rossi", "submitted_at": "2026-11-27T11:00:00+00:00",
            "doers": [{"part": "governance", "person_subject": BOB, "person_name": "Bob Rossi",
                       "first_saved_at": "2026-11-27T10:40:00+00:00"}],
            "sign_offs": [{"signer_subject": "carla-subject", "signer_name": "Carla Bianchi", "answer": "send_back",
                           "reason": "Say who decides", "content_hash": "bad", "card_state": None,
                           "at": "2026-11-27T10:50:00+00:00"}],
            "holding": True, "parts": [], "may": {"take": True, "take_over": False, "sign": sign},
            "page": "/controls/p/demo/submissions/s1"}


def on_sign(tmp_path, body, steps=(), **answers):
    return run_page(tmp_path, "sign.html", search="?project=demo&kind=fill_checklist&subject=s1", steps=list(steps),
                    answers={"/api/projects/demo": {"status": 200, "body": {"name": "Demo", "slug": "demo"}},
                             TASK: {"status": 200, "body": body}, **answers})


def test_the_sign_off_page_shows_the_submitted_task_its_doers_and_earlier_sign_offs(tmp_path):
    out = on_sign(tmp_path, task_answer())
    shown = text(out)
    for said in ("Fill a checklist", "Bob Rossi", "c0ffee", "Carla Bianchi", "Say who decides", "governance"):
        assert said in shown, f"{said!r} not on the page: {shown}"
    assert ["Open the submitted content", "https://launcher.example/controls/p/demo/submissions/s1"] in out["links"]


def test_agree_signs_on_the_content_hash_the_page_showed(tmp_path):
    out = on_sign(tmp_path, task_answer(), steps=[{"click": "Agree"}],
                  **{TASK + "/sign": {"status": 200, "body": {"state": "done"}}})
    assert calls(out, "POST") == [(TASK + "/sign", {"answer": "agree", "content_hash": "c0ffee"})]


def test_send_back_sends_the_reason(tmp_path):
    out = on_sign(tmp_path, task_answer(), steps=[{"type": "Why it goes back", "value": "Name the board"},
                                                  {"click": "Send back"}],
                  **{TASK + "/sign": {"status": 200, "body": {"state": "open"}}})
    assert calls(out, "POST") == [(TASK + "/sign", {"answer": "send_back", "reason": "Name the board",
                                                    "content_hash": "c0ffee"})]


def test_a_refused_sign_off_says_the_platforms_words(tmp_path):
    moved = {"code": "upstream_moved", "message": "The content of Fill a checklist changed since it was shown to you."}
    out = on_sign(tmp_path, task_answer(), steps=[{"click": "Agree"}],
                  **{TASK + "/sign": {"status": 409, "body": {"detail": moved}}})
    assert moved["message"] in text(out)


def test_someone_who_may_not_sign_sees_the_task_and_no_buttons(tmp_path):
    out = on_sign(tmp_path, task_answer(sign=False))
    assert "Fill a checklist" in text(out)
    assert out["buttons"] == []


def test_the_project_page_leads_its_members_to_the_work_board_and_who_does_what(tmp_path):
    authz = {"verdict": "allow", "status": 200, "role": "viewer", "admin": False, "pid": "p1", "slug": "demo"}
    out = run_page(tmp_path, "project.html", pathname="/p/demo", answers={
        "/api/projects/demo": {"status": 200, "body": {"name": "Demo", "slug": "demo", "pid": "p1"}},
        "/api/authz/projects/demo": {"status": 200, "body": authz}})
    links = [href for _, href in out["links"]]
    assert "/work.html?project=demo" in links and "/rules.html?project=demo" in links, out["links"]
