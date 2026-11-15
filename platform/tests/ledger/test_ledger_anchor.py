"""The ledger's heads, verified and signed, for a copy kept outside the stack.

`platform_service.ledger.anchor.heads(store)` gives, for the platform log and each pool database assigned
to a project, the head the store holds now, checked against the state the platform last verified, with the
store's signature. `python -m platform_service.ledger.anchor` prints them as one JSON document, which
scripts/ledger-anchor.sh writes outside the stack every day. A head that does not verify raises, so a
tampered log is never anchored as if it were whole.
"""
from __future__ import annotations

import pytest

from tests.ledger.conftest import OWNER, log_of, needs_db, relay_all

pytestmark = needs_db


def anchor():
    try:
        from platform_service.ledger import anchor as module
    except ImportError:
        pytest.fail("there is no ledger anchor (platform_service.ledger.anchor)")
    return module


def _some_events(through_gateway, project, mode):
    mode("enforce")
    r = through_gateway(OWNER, "POST",
                        f"/projects/{project['slug']}/members",
                        json={"subject": "00000000-0000-0000-0000-0000000000d9", "role": "viewer"})
    assert r.status_code in (200, 201), r.text
    relay_all(project["pid"])


def test_heads_are_verified_and_carry_the_signature(project, memory_ledger, through_gateway, mode):
    _some_events(through_gateway, project, mode)
    heads = anchor().heads(memory_ledger)
    mine = [h for h in heads if h["project_pid"] == project["pid"]]
    assert len(mine) == 1, "the project's log has no anchored head"
    [head] = mine
    assert head["log"] == log_of(project["pid"])
    assert head["tx"] == memory_ledger.server_head(head["log"])["tx"] and head["hash"]
    assert head["signature_b64"] and head["verified_at"]
    assert any(h["project_pid"] is None for h in heads), "the platform log has no anchored head"


def test_a_tampered_head_raises(project, memory_ledger, through_gateway, mode):
    from platform_service.ledger.store import TamperAlarm

    _some_events(through_gateway, project, mode)
    memory_ledger.tamper(log_of(project["pid"]), 1, "action", "forged")
    with pytest.raises(TamperAlarm):
        anchor().heads(memory_ledger)


def test_the_command_prints_one_json_document(project, memory_ledger, through_gateway, mode, capsys):
    import json

    _some_events(through_gateway, project, mode)
    anchor().main([])
    document = json.loads(capsys.readouterr().out)
    assert set(document) == {"anchored_at", "heads"} and document["heads"]

