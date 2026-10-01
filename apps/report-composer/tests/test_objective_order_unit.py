"""The step 4 links are sent in catalogue order of their objective (2026-10-01): O9 before O10."""
from report_composer.evidence_links import _objective_order


def test_o9_before_o10_and_old_ids_last():
    assert sorted(["O10", "R1.1", "O9", "O1"], key=_objective_order) == ["O1", "O9", "O10", "R1.1"]
