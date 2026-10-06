"""Readiness on the evidence page equals the controls app's (apps/controls/src/lib/scoring.ts): "Not started"
(score 1) is 0% and "Fully implemented" (5) is 100%, the mean of (score - 1) / 4, rounded half up as
JavaScript's Math.round does (review pass 2026-10-06; it was mean / 5, so "Not started" read as 20%)."""
import pytest

from platform_service.evidence import readiness


@pytest.mark.parametrize("mean, expected", [(1, 0), (5, 100), (3, 50), (4.5, 88), (1.02, 1), (None, None)])
def test_readiness_runs_from_not_started_to_fully_implemented(mean, expected):
    assert readiness(mean) == expected
