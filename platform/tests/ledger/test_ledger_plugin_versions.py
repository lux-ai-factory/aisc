"""One version of a test's package is on in a project: the versions an install or a switch turns off are
named in the event that request already writes (details `turned_off`), so the ledger accepts it under that
request's route and item."""
import uuid

import pytest

from platform_service.ledger import registry


def event(action, item_id, details):
    return {"event_id": str(uuid.uuid4()), "request_id": str(uuid.uuid4()), "action": action,
            "item_type": "plugin", "item_id": item_id, "details": details}


@pytest.mark.parametrize("action, item_id, details", [
    ("plugin.installed", "demo-pkg", {"package": "demo-pkg", "version": "0.2.0", "reused": False,
                                      "turned_off": ["0.1.0"]}),
    ("engine.plugin.toggled", str(uuid.uuid4()), {"enabled": True, "turned_off": ["0.2.0"]}),
])
def test_the_versions_turned_off_are_accepted_in_the_requests_own_event(action, item_id, details):
    assert registry.check(event(action, item_id, details), emitter="engine") == []
