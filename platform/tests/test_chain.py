"""The platform's steps of the pipeline chain (scripts/test-pipeline-chain.sh, 03 WP12).

Skipped unless CHAIN_JSON names the chain's shared state. Step 1 makes the project
and card version 1; step 6 saves version 2. Both go through the API, as a user would.
The project's slug starts `chain-`, never `pytest-`: the suite's cleanup deletes
those at the end of every session (F14a).
"""
import json
import os
import uuid
from pathlib import Path

import pytest

CHAIN_JSON = os.environ.get("CHAIN_JSON")
pytestmark = [
    pytest.mark.chain,
    pytest.mark.skipif(not CHAIN_JSON, reason="not in the pipeline chain (CHAIN_JSON unset)"),
]

ALICE = "00000000-0000-0000-0000-00000000a11c"


def _state() -> dict:
    return json.loads(Path(CHAIN_JSON).read_text())


def _write(**keys) -> None:
    state = _state()
    state.update(keys)
    Path(CHAIN_JSON).write_text(json.dumps(state))


def test_chain_step1_project_and_v1(client, as_user):
    slug = f"chain-{uuid.uuid4().hex[:12]}"
    made = client.post("/projects", json={"name": slug, "slug": slug}, headers=as_user(ALICE))
    assert made.status_code == 201, made.text
    project = made.json()
    v1 = client.post(f"/projects/{slug}/system-versions",
                     json={"name": "MCAS", "version": "1.2.0", "provider": "LIST"},
                     headers=as_user(ALICE))
    assert v1.status_code == 201, v1.text
    assert v1.json()["number"] == 1
    _write(project_pid=str(project["pid"]), project_slug=slug, v1_pid=v1.json()["pid"])


def test_chain_step6_v2(client, as_user):
    state = _state()
    v2 = client.post(f"/projects/{state['project_slug']}/system-versions",
                     json={"name": "MCAS", "version": "1.3.0", "provider": "LIST"},
                     headers=as_user(ALICE))
    assert v2.status_code == 201, v2.text
    assert v2.json()["number"] == 2
    _write(v2_pid=v2.json()["pid"])
