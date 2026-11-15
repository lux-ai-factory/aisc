"""A test fetched and published on install is installed in the engine with the sha256 of the wheel the
publisher published, so the engine installs exactly that wheel and records it. Runs on the throwaway; the
public catalogue, the engine, the index and the publisher are local fakes."""
from __future__ import annotations

from tests.conftest import needs_database
from tests.test_catalogue_choice import (admin, choose, engine, engine_like_the_real_one, evidence_project,  # noqa: F401
                                         index, public, publisher, url)
from tests.test_evidence import _reader, catalogue  # noqa: F401  (fixtures)

pytestmark = needs_database
PUBLISHED = "c" * 64


def test_a_catalogue_install_hands_the_engine_the_published_wheels_hash(
        client, as_user, evidence_project, public, engine, index, publisher):  # noqa: F811
    publisher.route("POST", "/publish", (200, {"package": "data-monitor", "version": "0.3.2", "published": True,
                                               "sha256": PUBLISHED}))
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    engine_like_the_real_one(engine, publisher, evidence_project)
    r = client.post(url(evidence_project, "/api/tool/snt-data-drift/install"), headers=admin(as_user))
    assert r.status_code == 200, r.text
    sent = engine.requests("POST", "/api/v1/plugins")[-1]["json"]
    assert sent.get("wheel_sha256") == PUBLISHED, sorted(sent)
