"""The provider's risk measures that a migration dropped from every card version are restored from the
ledger's own copies of the cards: each qualification.created or qualification.amended event in a project's
ledger.outbox carries the card it saved, risks and measures included. The command reads them into an
archive and writes only when told --yes; declaring the restore in the ledger is a separate step.

The command is `scripts/restore-dropped-risk-measures.py`; these tests feed it fake ledger rows only.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/restore-dropped-risk-measures.py"


def _command():
    assert SCRIPT.is_file(), f"{SCRIPT.relative_to(ROOT)} does not exist"
    spec = importlib.util.spec_from_file_location("restore_dropped_risk_measures", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _event(event_id, action, card_id, risks, occurred_at="2026-10-28T10:00:00+00:00"):
    return {"event_id": event_id, "action": action, "item_id": card_id, "occurred_at": occurred_at,
            "content": {"systemName": "Fake system", "risks": risks}}


RISK_WITH_MEASURES = {"position": 0, "risk": "Wrong match", "control": "Human review of every match",
                      "controlTerm": "vair:HumanOversight", "followUpControl": "Escalate to a caseworker",
                      "followUpControlTerm": None}
RISK_WITHOUT = {"position": 1, "risk": "Outage", "control": "", "followUpControl": ""}


def test_measures_are_read_from_the_cards_the_ledger_holds():
    rows = _command().measures_from_events([
        _event("e1", "qualification.created", "card-1", [RISK_WITH_MEASURES, RISK_WITHOUT]),
    ])
    assert rows == [{
        "qualification_id": "card-1", "position": 0, "control": "Human review of every match",
        "control_term": "vair:HumanOversight", "follow_up_control": "Escalate to a caseworker",
        "follow_up_control_term": None, "source_event_id": "e1",
    }]


def test_a_correction_is_read_as_its_own_card():
    rows = _command().measures_from_events([
        _event("e1", "qualification.created", "card-1", [RISK_WITH_MEASURES]),
        _event("e2", "qualification.amended", "card-1b", [RISK_WITH_MEASURES]),
    ])
    assert sorted(r["qualification_id"] for r in rows) == ["card-1", "card-1b"]


def test_other_events_and_cards_without_measures_give_nothing():
    rows = _command().measures_from_events([
        _event("e3", "qualification.opened", "card-1", [RISK_WITH_MEASURES]),
        _event("e4", "qualification.created", "card-2", [RISK_WITHOUT]),
    ])
    assert rows == []


def test_the_command_writes_only_when_told_yes():
    source = SCRIPT.read_text() if SCRIPT.is_file() else ""
    assert "--yes" in source, "the restore must default to a dry run and write only with --yes"
