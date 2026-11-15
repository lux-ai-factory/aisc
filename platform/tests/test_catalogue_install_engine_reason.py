"""An install the engine refuses because the eval worker could not read the test's manifest says why.

The engine waits PLUGIN_MANIFEST_TIMEOUT_S (900 seconds by default) for the worker, then answers 503 with a named
reason. The platform waits longer than that for the install call, so the person reads the engine's reason, not a
timeout of the platform's own. Runs on the throwaway; the public catalogue, the engine and the index are local
fakes.
"""
from __future__ import annotations

from tests.conftest import needs_database
from tests.test_catalogue_choice import (ENGINE_PID, admin, choose, engine, evidence_project, index,  # noqa: F401
                                         public, url)
from tests.test_evidence import _reader, catalogue  # noqa: F401  (fixtures)

pytestmark = needs_database

NOT_READ = "the plugin's declarations could not be read: the worker did not answer within 900 seconds"


def test_the_engines_named_reason_reaches_the_person_when_the_worker_could_not_read_the_manifest(
        client, as_user, evidence_project, public, engine, index):  # noqa: F811
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    engine.route("POST", f"/api/v1/projects/for-platform/{evidence_project['pid']}",
                 (200, {"pid": ENGINE_PID, "name": "evd"}))
    engine.route("POST", "/api/v1/plugins", (503, {"detail": NOT_READ}))

    r = client.post(url(evidence_project, "/api/tool/langbite/install"), headers=admin(as_user))
    assert r.status_code == 503, r.text
    assert NOT_READ in r.json()["detail"], r.json()
