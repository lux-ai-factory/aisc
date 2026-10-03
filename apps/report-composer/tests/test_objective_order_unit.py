"""The step 4 links are sent in catalogue order of their objective: O9 before O10."""
from report_composer.evidence_links import _objective_order


def test_o9_before_o10_and_old_ids_last():
    assert sorted(["O10", "R1.1", "O9", "O1"], key=_objective_order) == ["O1", "O9", "O10", "R1.1"]


def test_a_projects_own_sets_sort_after_the_built_in_one_by_code_then_number():
    assert sorted(["BNK10", "O24", "BNK9", "AAA1", "O3"], key=_objective_order) == ["O3", "O24", "AAA1", "BNK9", "BNK10"]
