"""What the evaluation form's target dropdown says: where each target comes from and how it is reached."""
import pytest

from platform_service import targets

SYSTEM = {"kind": "system", "label": "MCAS", "component_kind": None, "last_card_number": None}
MODEL = {"kind": "component", "label": "Scoring model", "component_kind": "model", "last_card_number": 2}


@pytest.mark.parametrize("kind, protocol", [
    ("openai", "OpenAI-compatible"), ("rest", "REST API"), ("a2a", "A2A agent"), ("oip", "Open Inference Protocol")])
def test_a_connected_target_names_its_protocol(kind, protocol):
    assert targets.mirror_name(SYSTEM, {"name": "chat", "kind": kind}) == f"AI card · System: MCAS · reached through {protocol}"


def test_a_target_without_a_connection_says_so():
    assert targets.mirror_name(SYSTEM, None) == "AI card · System: MCAS · not connected"
    assert targets.mirror_name(MODEL, None, latest_card=2) == "AI card · Component: Scoring model (model) · not connected"


def test_a_component_the_latest_card_dropped_says_which_card():
    assert targets.mirror_name(MODEL, None, latest_card=3) == \
        "AI card · Component: Scoring model (model) · not connected · not in AI card v3"
    assert targets.mirror_name(MODEL, {"name": "m", "kind": "rest"}, latest_card=3) == \
        "AI card · Component: Scoring model (model) · reached through REST API · not in AI card v3"
