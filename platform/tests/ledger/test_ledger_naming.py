"""L2: one immudb database per project, named by one rule (I9). A pid is what `projects.PID` accepts
(a dashed UUID); the name is its lowercase hex (R4.2)."""
from __future__ import annotations

import pytest

from platform_service.ledger.naming import PLATFORM_DB, database_name


def test_a_project_has_its_own_database():
    assert database_name("5d3f5f2a-ac34-414b-ae8d-3df80dfe8df3") == "ledger5d3f5f2aac34414bae8d3df80dfe8df3"


def test_the_case_of_a_dashed_pid_does_not_matter():
    assert database_name("5D3F5F2A-AC34-414B-AE8D-3DF80DFE8DF3") == "ledger5d3f5f2aac34414bae8d3df80dfe8df3"


@pytest.mark.parametrize("bad", ["", "mcas", "../x", "5d3f5f2a-ac34-414b-ae8d-3df80dfe8df3;drop",
                                 "5d3f5f2a-ac34-414b-ae8d", None,
                                 "5d3f5f2aac34414bae8d3df80dfe8df3",          # undashed: projects.PID refuses it
                                 "00000000-0000-0000-0000-000000000000"])     # the nil UUID
def test_anything_but_a_pid_is_refused(bad):
    with pytest.raises((ValueError, TypeError)):
        database_name(bad)


def test_the_platforms_own_events_have_their_own_database():
    assert PLATFORM_DB == "ledgerplatform"
