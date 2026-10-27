"""Start moves the engine's old helper components to the platform (manage.py move_helper_models).

On an older install a judge was an `llm` component of the engine's AI system. After the local controls
step, start asks the engine to hand those a run used as helpers to the platform's helper models and
prints what it moved and what it left. A move that fails is a warning: the stack is up all the same.
"""
from test_start_script import calls, run, scratch  # noqa: F401 - scratch is a fixture

MOVE = "exec -T aisc-backend python manage.py move_helper_models"
CATALOGUE = "exec -T platform python -m platform_service.catalogue"


def test_start_runs_move_after_catalogue_step(scratch):  # noqa: F811
    (scratch / "local-controls").write_text("moved 1\nleft 1: MCAS/sut-llm\n")   # every exec answers this
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    asked = [c for c in calls(scratch) if " exec " in c]
    assert len(asked) == 2 and CATALOGUE in asked[0] and MOVE in asked[1]
    assert "left 1: MCAS/sut-llm" in r.stdout


def test_a_move_that_fails_is_a_warning_and_the_start_goes_on(scratch):  # noqa: F811
    r = run(scratch)                                  # every exec fails: no local-controls file
    assert r.returncode == 0, r.stdout + r.stderr
    assert "old helper models could not be moved" in r.stdout and "AISC is up" in r.stdout
